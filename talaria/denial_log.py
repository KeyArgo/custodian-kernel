"""Denial log — a tamper-evident record of everything the agent tried
that it wasn't allowed to do.

This is the user-facing "log what it attempted when I said no." Every
DENY (and optionally WARN) from the guard-adapter pipeline lands here,
hash-chained and HMAC-signed so the log can't be quietly edited or
truncated after the fact — a real receipt of "the agent tried to read
~/.ssh, and we stopped it."

It reuses warden's already-proven :class:`warden.audit.AuditLog`
(hash-chained JSONL) verbatim rather than reinventing the chain — the
denial log is just an audit log with denial-shaped records mapped onto
its (event, ref, requester, band, detail) columns:

    event     = "deny" | "warn"
    ref       = the tool/skill the agent tried to use
    requester = the guard adapter that stopped it
    band      = "-"  (not spend-related)
    detail    = the human reason (already value-free by adapter design)

The log is value-free: adapters never put secret material or full
forbidden file *contents* in a Verdict reason, so nothing sensitive
reaches disk here — only *that* an attempt was made and why it was
refused.

Wiring: build_observer() returns a callback matching
``custodian.adapters.pipeline.VerdictObserver``; hand it to an
AdapterPipeline (or the Hermes plugin) and denials persist automatically.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from warden import crypto
from warden.audit import AuditLog

LOG_FILENAME = "denials.jsonl"
KEY_FILENAME = "denial.key"


def _default_dir() -> Path:
    """Call-time resolution so TALARIA_HOME set after import is honored."""
    return Path(os.environ.get("TALARIA_HOME", "~/.talaria")).expanduser()


def _ensure_key(key_path: Path) -> bytes:
    """Load the denial-log HMAC key, generating a fresh 32-byte one (0600)
    on first use. This key only protects log *integrity* (tamper-evidence),
    not confidentiality — the log is value-free — so a locally-generated
    key with no passphrase is the right tradeoff for "just works".

    Two processes racing on first use (e.g. two Hermes instances starting
    simultaneously) can both pass the exists() check before either
    creates the file — found in review. The loser's O_EXCL open then
    raises FileExistsError; instead of crashing, it falls through to
    reading back the key the winner just wrote."""
    key_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(key_path.parent, 0o700)
    if key_path.exists():
        return key_path.read_bytes()
    key = os.urandom(crypto.KEY_LEN)
    try:
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return key_path.read_bytes()
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


class DenialLog:
    """Tamper-evident log of denied (and optionally warned) agent actions."""

    def __init__(self, dir_path: Optional[Path] = None, log_warns: bool = False) -> None:
        self.dir = Path(dir_path) if dir_path else _default_dir()
        self.log_warns = log_warns
        key = _ensure_key(self.dir / KEY_FILENAME)
        self._audit = AuditLog(self.dir / LOG_FILENAME, key)

    @property
    def path(self) -> Path:
        return self._audit.path

    def record(self, skill: str, adapter: str, reason: str, event: str = "deny") -> None:
        """Best-effort: the guard's DENY/WARN verdict already happened and
        already enforced the policy — this log entry is a side-channel
        audit trail, not the enforcement itself. A disk-full or
        permission failure here must not raise (the pipeline's observer
        call site swallows exceptions anyway — see pipeline.py's
        _notify), but silently losing the entry with zero signal was a
        real gap found in review. Surface it as a warning instead."""
        try:
            self._audit.append(event=event, ref=skill or "-", requester=adapter or "-",
                               band="-", detail=reason or "")
        except Exception as e:
            import warnings
            warnings.warn(f"talaria denial log: failed to record {event!r} "
                          f"for skill {skill!r}: {e}", stacklevel=2)

    def records(self) -> list[dict]:
        return self._audit.records()

    def verify(self) -> int:
        """Walk the chain; raises AuditChainBrokenError on the first break."""
        return self._audit.verify()

    def observer(self):
        """Return a VerdictObserver callback that records DENY (and, if
        log_warns, WARN) verdicts as they happen."""
        from custodian.adapters.base import Decision

        def _obs(ctx, verdict) -> None:
            if verdict.decision == Decision.DENY:
                self.record(ctx.skill, verdict.adapter,
                            verdict.reason or verdict.transform_note, event="deny")
            elif verdict.decision == Decision.WARN and self.log_warns:
                self.record(ctx.skill, verdict.adapter, verdict.reason, event="warn")

        return _obs
