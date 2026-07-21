"""The universal ledger — one append-only, hash-chained, tamper-evident
record of every governed action, money or not, shipped inside the kernel
itself (not an integration add-on).

Why this exists and what it replaces: three separate, uncoordinated
persistence paths already existed before this module --
``custodian.audit.AuditLog`` (a JSONL writer with zero call sites --
dead code), ``SqliteStorage``'s ``audit_log`` table (the one actually
used by the CLI, but money-shaped only -- ``event``/``amount``/``band``,
no room for a non-money governed action, no tamper evidence at all), and
the ``stripe-spend`` skill's own private JSONL writer
(``bundled_skills/payments/stripe-spend/scripts/_core.py``). This module
is the one going forward. It does not delete the others yet -- existing
CLI commands keep reading ``audit_log`` until they're migrated -- but
every new call site should write here.

Crash safety, honestly: this is a SQLite table in WAL mode, using
``BEGIN IMMEDIATE`` so the tip-read, digest-compute, and insert happen
inside one atomic transaction -- the write lock is acquired before the
tip is even read, so two writers can never compute a link from the same
tip (the exact bug paladin.audit.AuditLog's docstring documents as a
known, unresolved gap for *that* module: "cross-process racing is a
separate concern"). SQLite's own WAL engine already solves short-write
and torn-page recovery; this module does not need to reimplement them.

What this does NOT claim: a local hash chain alone does not prove the
tail was never truncated by someone with full file access who
regenerates a shorter, internally-consistent chain from genesis --
that requires an external, signed checkpoint this module does not yet
produce. Say so rather than imply otherwise. The same limitation applies
to content, not just length: ``verify()`` proves the chain is
internally self-consistent, not that every row was ever produced by
``append()``/``_validate()`` -- someone with direct write access to the
SQLite file can fabricate a row with a correctly self-computed digest
that never passed sanitization. ``_validate()`` is a guard against
accidental or buggy application-level calls, not a defense against an
attacker who already has local file access to the ledger itself; that
threat is the same one the truncation limitation above already names.

Schema is intentionally provider-neutral: ``provider``/``action`` name
what happened, ``lifecycle_event`` names where in the propose -> decide
-> escalate -> approve/deny -> execute -> verify sequence this record
sits, and ``metadata`` is a bounded, explicit allow-list of primitive
values -- never a raw args dict, never a prompt, never a credential
value. ``credential_refs`` holds ``paladin://name`` reference strings
only, enforced at the API boundary, never resolved values.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from custodian.exceptions import AuditWriteError, StorageError

SCHEMA_VERSION = 1
GENESIS_FALLBACK = "0" * 64  # used only if the installation marker can't be read/created

_LIFECYCLE_EVENTS = frozenset({
    "proposed", "decided", "escalated", "approved", "denied",
    "credential_authorized", "executed", "failed", "verified",
})
_VERDICTS = frozenset({"autonomous", "escalation_required", "denied", None})

_REF_RE = re.compile(r"^paladin://[a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127}$")
_MAX_METADATA_BYTES = 4096
_MAX_METADATA_KEYS = 32

# Every string field has a bound, not just metadata -- found in review:
# fields outside this list (external_id, approver, band, currency,
# destination_host, receipt_ref, ...) had no length check at all, so a
# 500KB string passed _validate() and was written to disk verbatim,
# directly contradicting this module's own claim of being bounded.
_MAX_FIELD_LEN = {
    "correlation_id": 128, "session_id": 128, "requester": 256,
    "provider": 128, "action": 256, "band": 16, "approver": 256,
    "currency": 8, "external_id": 256, "destination_host": 256,
    "receipt_ref": 256,
}

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            TEXT    NOT NULL UNIQUE,
    schema_version      INTEGER NOT NULL,
    ts                  REAL    NOT NULL,
    correlation_id      TEXT    NOT NULL,
    session_id          TEXT    NOT NULL,
    requester           TEXT    NOT NULL,
    provider            TEXT    NOT NULL,
    action               TEXT    NOT NULL,
    lifecycle_event     TEXT    NOT NULL,
    verdict             TEXT,
    band                TEXT,
    approver            TEXT,
    amount              REAL,
    currency            TEXT,
    cost_estimated      REAL,
    cost_actual         REAL,
    external_id         TEXT,
    credential_refs     TEXT,
    destination_host    TEXT,
    metadata            TEXT,
    receipt_ref         TEXT,
    prev_digest         TEXT    NOT NULL,
    digest              TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_correlation ON ledger_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_ledger_provider ON ledger_events(provider);
CREATE INDEX IF NOT EXISTS idx_ledger_requester ON ledger_events(requester);
CREATE INDEX IF NOT EXISTS idx_ledger_event ON ledger_events(lifecycle_event);
CREATE INDEX IF NOT EXISTS idx_ledger_ts ON ledger_events(ts);
CREATE INDEX IF NOT EXISTS idx_ledger_external ON ledger_events(external_id);
CREATE TABLE IF NOT EXISTS ledger_installation (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    genesis     TEXT    NOT NULL,
    created_at  REAL    NOT NULL
);
"""


class LedgerChainBrokenError(StorageError):
    """verify() found a tampered, reordered, or truncated chain."""


class LedgerValidationError(AuditWriteError):
    """A record failed the sanitization/shape checks at the write boundary."""


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _secret_shape_label(text: str) -> Optional[str]:
    """Reuses the kernel's own secret-format patterns (Stripe/AWS/GitHub/
    Slack/OpenAI/JWT/private-key-block/etc, plus the punctuation-boundary
    fix from this session's adversarial pass) rather than a second,
    divergent regex list -- found in review: metadata was type/size
    checked but never content-scanned, so a real credential shape passed
    validation and was written to disk verbatim, directly contradicting
    this module's own docstring promise. Import is local to avoid making
    the ledger module's import graph depend on the adapters package at
    module-load time for callers that never touch metadata scanning."""
    from custodian.adapters.builtin.secret_leak_guard import _PATTERNS
    for pattern, label in _PATTERNS:
        if pattern.search(text):
            return label
    return None


@dataclass
class LedgerEvent:
    """One normalized record. Construct with only what you know --
    everything except correlation_id/requester/provider/action/
    lifecycle_event is optional and typically None on a `proposed`
    record, filled in on later records sharing the same correlation_id."""

    correlation_id: str
    requester: str
    provider: str
    action: str
    lifecycle_event: str
    session_id: str = "default"
    verdict: Optional[str] = None
    band: Optional[str] = None
    approver: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    cost_estimated: Optional[float] = None
    cost_actual: Optional[float] = None
    external_id: Optional[str] = None
    credential_refs: tuple = ()
    destination_host: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    receipt_ref: Optional[str] = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)

    def _validate(self) -> None:
        if self.lifecycle_event not in _LIFECYCLE_EVENTS:
            raise LedgerValidationError(
                f"lifecycle_event {self.lifecycle_event!r} not one of {sorted(_LIFECYCLE_EVENTS)}"
            )
        if self.verdict not in _VERDICTS:
            raise LedgerValidationError(f"verdict {self.verdict!r} not one of {sorted(v for v in _VERDICTS if v)}")
        for ref in self.credential_refs:
            if not _REF_RE.match(ref):
                raise LedgerValidationError(
                    f"credential_refs must be paladin:// reference names only, got {ref!r} -- "
                    "never a resolved value"
                )

        # Bound + secret-scan every plain string field, not only metadata --
        # found in review: a 500KB (or credential-shaped) string in
        # external_id/approver/band/currency/destination_host/receipt_ref
        # had nothing checking it at all.
        for name, max_len in _MAX_FIELD_LEN.items():
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str):
                raise LedgerValidationError(f"{name} must be a string, got {type(value).__name__}")
            if len(value) > max_len:
                raise LedgerValidationError(f"{name} is {len(value)} chars, max {max_len}")
            label = _secret_shape_label(value)
            if label is not None:
                raise LedgerValidationError(
                    f"{name} looks like a credential ({label}) -- the ledger never stores "
                    f"secret values, only paladin:// reference names via credential_refs"
                )

        if not isinstance(self.metadata, dict):
            raise LedgerValidationError("metadata must be a dict of primitive values")
        if len(self.metadata) > _MAX_METADATA_KEYS:
            raise LedgerValidationError(f"metadata has {len(self.metadata)} keys, max {_MAX_METADATA_KEYS}")
        for k, v in self.metadata.items():
            if not isinstance(k, str):
                raise LedgerValidationError("metadata keys must be strings")
            if not isinstance(v, (str, int, float, bool)) and v is not None:
                raise LedgerValidationError(
                    f"metadata[{k!r}] is {type(v).__name__}, not a primitive -- "
                    "the ledger never stores raw args, prompts, or nested structures"
                )
            if isinstance(v, str):
                label = _secret_shape_label(v)
                if label is not None:
                    raise LedgerValidationError(
                        f"metadata[{k!r}] looks like a credential ({label}) -- the ledger "
                        f"never stores secret values, only paladin:// reference names"
                    )
        encoded = _canonical(self.metadata)
        if len(encoded) > _MAX_METADATA_BYTES:
            raise LedgerValidationError(
                f"metadata is {len(encoded)} bytes, max {_MAX_METADATA_BYTES} -- "
                "the ledger is not a place to dump provider payloads"
            )

    def _body(self) -> dict:
        return {
            "event_id": self.event_id,
            "schema_version": SCHEMA_VERSION,
            "ts": self.ts,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "requester": self.requester,
            "provider": self.provider,
            "action": self.action,
            "lifecycle_event": self.lifecycle_event,
            "verdict": self.verdict,
            "band": self.band,
            "approver": self.approver,
            "amount": self.amount,
            "currency": self.currency,
            "cost_estimated": self.cost_estimated,
            "cost_actual": self.cost_actual,
            "external_id": self.external_id,
            "credential_refs": list(self.credential_refs),
            "destination_host": self.destination_host,
            "metadata": self.metadata,
            "receipt_ref": self.receipt_ref,
        }


class UniversalLedger:
    """Append-only, hash-chained ledger. One instance per SQLite file;
    safe to construct one per call the way SqliteStorage already is --
    WAL mode makes that the cheap, correct pattern here too."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(self.path))
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA_SQL)
            # Origin-bound genesis: a fixed literal ("0"*64) meant every
            # ledger anywhere started from the identical value, so nothing
            # tied a chain to a specific installation -- found in review
            # against docs/MODULAR_PLATFORM_HANDOVER.md's explicit
            # "origin-bound genesis" requirement. Generated once per
            # database file and stored alongside it. INSERT OR IGNORE +
            # re-SELECT (not INSERT OR REPLACE) so two processes racing to
            # create the same brand-new file agree on one winner instead
            # of one silently overwriting the other's genesis after some
            # events may already chain from it.
            conn.execute(
                "INSERT OR IGNORE INTO ledger_installation (id, genesis, created_at) "
                "VALUES (1, ?, ?)",
                (uuid.uuid4().hex + uuid.uuid4().hex, time.time()),
            )
            conn.commit()
            row = conn.execute("SELECT genesis FROM ledger_installation WHERE id = 1").fetchone()
            conn.close()
        except sqlite3.Error as e:
            raise StorageError(f"failed to initialize ledger at {self.path}: {e}") from e
        self.genesis = row[0] if row else GENESIS_FALLBACK

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def append(self, event: LedgerEvent) -> str:
        """Append one event, return its digest. Raises LedgerValidationError
        before any write if the record fails sanitization -- validation
        happens outside the transaction so a bad record never holds the
        write lock."""
        event._validate()
        try:
            conn = self._connect()
            try:
                # BEGIN IMMEDIATE acquires the write lock before the tip is
                # read, not after -- two connections both computing a link
                # from the same tip (and one silently losing) is exactly
                # the race a plain SELECT-then-INSERT would allow under
                # concurrent writers. This is the "one lock across
                # tip-read + link + append" property.
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT digest FROM ledger_events ORDER BY id DESC LIMIT 1"
                ).fetchone()
                prev_digest = row["digest"] if row is not None else self.genesis
                body = event._body()
                digest = hashlib.sha256(prev_digest.encode() + _canonical(body)).hexdigest()
                conn.execute(
                    """INSERT INTO ledger_events (
                        event_id, schema_version, ts, correlation_id, session_id,
                        requester, provider, action, lifecycle_event, verdict, band,
                        approver, amount, currency, cost_estimated, cost_actual,
                        external_id, credential_refs, destination_host, metadata,
                        receipt_ref, prev_digest, digest
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        body["event_id"], body["schema_version"], body["ts"],
                        body["correlation_id"], body["session_id"], body["requester"],
                        body["provider"], body["action"], body["lifecycle_event"],
                        body["verdict"], body["band"], body["approver"], body["amount"],
                        body["currency"], body["cost_estimated"], body["cost_actual"],
                        body["external_id"], json.dumps(body["credential_refs"]),
                        body["destination_host"], json.dumps(body["metadata"]),
                        body["receipt_ref"], prev_digest, digest,
                    ),
                )
                conn.commit()
                return digest
            finally:
                conn.close()
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to append ledger event at {self.path}: {e}") from e

    def verify(self) -> None:
        """Walk the whole chain and recompute every digest. Raises
        LedgerChainBrokenError on the first break -- an edited field, a
        reordered row, a deleted row, or a digest that doesn't match its
        own recomputation. Does NOT prove the tail was never truncated
        by someone with full file access who regenerates a shorter chain
        from genesis -- that needs an external signed checkpoint, not
        built yet. Say so rather than imply full tamper-proofing."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM ledger_events ORDER BY id ASC").fetchall()
        finally:
            conn.close()
        expected_prev = self.genesis
        for row in rows:
            body = {
                "event_id": row["event_id"], "schema_version": row["schema_version"],
                "ts": row["ts"], "correlation_id": row["correlation_id"],
                "session_id": row["session_id"], "requester": row["requester"],
                "provider": row["provider"], "action": row["action"],
                "lifecycle_event": row["lifecycle_event"], "verdict": row["verdict"],
                "band": row["band"], "approver": row["approver"], "amount": row["amount"],
                "currency": row["currency"], "cost_estimated": row["cost_estimated"],
                "cost_actual": row["cost_actual"], "external_id": row["external_id"],
                "credential_refs": json.loads(row["credential_refs"]),
                "destination_host": row["destination_host"],
                "metadata": json.loads(row["metadata"]),
                "receipt_ref": row["receipt_ref"],
            }
            if row["prev_digest"] != expected_prev:
                raise LedgerChainBrokenError(
                    f"row {row['id']} (event {row['event_id']}): prev_digest does not "
                    f"match the actual previous row's digest -- chain broken (reordered "
                    f"or deleted row)"
                )
            recomputed = hashlib.sha256(expected_prev.encode() + _canonical(body)).hexdigest()
            if recomputed != row["digest"]:
                raise LedgerChainBrokenError(
                    f"row {row['id']} (event {row['event_id']}): stored digest does not "
                    f"match recomputed digest -- a field was edited after the fact"
                )
            expected_prev = row["digest"]

    # -- queries -----------------------------------------------------------

    def _query(self, where: str, params: tuple, limit: Optional[int]) -> Iterator[dict]:
        conn = self._connect()
        try:
            sql = f"SELECT * FROM ledger_events WHERE {where} ORDER BY id DESC"
            if limit:
                sql += " LIMIT ?"
                params = params + (limit,)
            for row in conn.execute(sql, params).fetchall():
                d = dict(row)
                d["credential_refs"] = json.loads(d["credential_refs"])
                d["metadata"] = json.loads(d["metadata"])
                yield d
        finally:
            conn.close()

    def by_correlation_id(self, correlation_id: str) -> list[dict]:
        return list(self._query("correlation_id = ?", (correlation_id,), None))

    def by_provider(self, provider: str, limit: Optional[int] = None) -> list[dict]:
        return list(self._query("provider = ?", (provider,), limit))

    def by_requester(self, requester: str, limit: Optional[int] = None) -> list[dict]:
        return list(self._query("requester = ?", (requester,), limit))

    def by_lifecycle_event(self, lifecycle_event: str, limit: Optional[int] = None) -> list[dict]:
        return list(self._query("lifecycle_event = ?", (lifecycle_event,), limit))

    def by_verdict(self, verdict: str, limit: Optional[int] = None) -> list[dict]:
        return list(self._query("verdict = ?", (verdict,), limit))

    def by_external_id(self, external_id: str) -> list[dict]:
        return list(self._query("external_id = ?", (external_id,), None))

    def in_time_range(self, start_ts: float, end_ts: float, limit: Optional[int] = None) -> list[dict]:
        return list(self._query("ts >= ? AND ts <= ?", (start_ts, end_ts), limit))

    def tail(self, limit: int = 50) -> list[dict]:
        return list(self._query("1 = 1", (), limit))
