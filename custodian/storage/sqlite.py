"""SQLite-backed storage backend.

Uses WAL mode and a connection-per-call pattern (open, do work, close) so
that concurrent readers never block writers. WAL mode permits one writer
and multiple simultaneous readers without lock contention, which maps
cleanly to the agent's workload (one spend at a time, possible concurrent
CLI reads for status).

The schema is intentionally simple: three tables, each with at most one
"significant" row (authority_state and pending_approval enforce single-row
with a CHECK(id=1) constraint). Audit entries are auto-incrementing rows.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from custodian.exceptions import StorageError
from custodian.storage.base import StorageBackend
from custodian.types import AuditEntry, AuthorityState, KillSwitchState, PendingApproval

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS authority_state (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    band        TEXT    NOT NULL,
    per_action_cap REAL NOT NULL,
    session_cap REAL    NOT NULL,
    spent_this_session REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event           TEXT    NOT NULL,
    amount          REAL    NOT NULL,
    description     TEXT    NOT NULL,
    band            TEXT    NOT NULL,
    ts              REAL    NOT NULL,
    approved_by     TEXT,
    denied_by       TEXT,
    payment_intent_id TEXT,
    stripe_status   TEXT,
    reason          TEXT,
    error           TEXT,
    recipe          TEXT,
    recipe_result   TEXT,
    recipe_error    TEXT
);

CREATE TABLE IF NOT EXISTS pending_approval (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    amount      REAL    NOT NULL,
    description TEXT    NOT NULL,
    reason      TEXT    NOT NULL DEFAULT '',
    created_at  REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS kill_switch (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    killed      INTEGER NOT NULL DEFAULT 0,
    reason      TEXT    NOT NULL DEFAULT '',
    by          TEXT    NOT NULL DEFAULT '',
    changed_at  REAL    NOT NULL
);
"""


class SqliteStorage(StorageBackend):
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(path))
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.executescript(_SCHEMA_SQL)
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise StorageError(f"failed to initialize SQLite storage at {path}: {e}") from e

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        return conn

    def load_authority_state(self) -> Optional[AuthorityState]:
        try:
            conn = self._connect()
            row = conn.execute("SELECT * FROM authority_state WHERE id = 1").fetchone()
            conn.close()
            if row is None:
                return None
            return AuthorityState(
                band=row["band"],
                per_action_cap=row["per_action_cap"],
                session_cap=row["session_cap"],
                spent_this_session=row["spent_this_session"],
            )
        except sqlite3.Error as e:
            raise StorageError(f"failed to load authority state: {e}") from e

    def save_authority_state(self, state: AuthorityState) -> None:
        try:
            conn = self._connect()
            conn.execute(
                "INSERT OR REPLACE INTO authority_state "
                "(id, band, per_action_cap, session_cap, spent_this_session) "
                "VALUES (1, ?, ?, ?, ?)",
                (state.band.value, state.per_action_cap,
                 state.session_cap, state.spent_this_session),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise StorageError(f"failed to save authority state: {e}") from e

    def append_audit_entry(self, entry: AuditEntry) -> None:
        record = entry.to_dict()
        record.setdefault("ts", time.time())
        try:
            conn = self._connect()
            conn.execute(
                "INSERT INTO audit_log "
                "(event, amount, description, band, ts, "
                "approved_by, denied_by, payment_intent_id, stripe_status, "
                "reason, error, recipe, recipe_result, recipe_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["event"], record["amount"], record["description"],
                    record["band"], record["ts"],
                    record.get("approved_by"), record.get("denied_by"),
                    record.get("payment_intent_id"), record.get("stripe_status"),
                    record.get("reason"), record.get("error"),
                    record.get("recipe"), record.get("recipe_result"),
                    record.get("recipe_error"),
                ),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise StorageError(f"failed to append audit entry: {e}") from e

    def read_audit_entries(self, limit: Optional[int] = None) -> list[AuditEntry]:
        try:
            conn = self._connect()
            sql = "SELECT * FROM audit_log ORDER BY id ASC"
            if limit is not None:
                sql += f" LIMIT {limit}"
            rows = conn.execute(sql).fetchall()
            conn.close()
            result = []
            for row in rows:
                d = dict(row)
                # sqlite3.Row uses column names as keys, pass as-is to from_dict
                result.append(AuditEntry.from_dict(d))
            return result
        except sqlite3.Error as e:
            raise StorageError(f"failed to read audit entries: {e}") from e

    def get_pending_approval(self) -> Optional[PendingApproval]:
        try:
            conn = self._connect()
            row = conn.execute("SELECT * FROM pending_approval WHERE id = 1").fetchone()
            conn.close()
            if row is None:
                return None
            return PendingApproval.from_dict(dict(row))
        except sqlite3.Error as e:
            raise StorageError(f"failed to get pending approval: {e}") from e

    def set_pending_approval(self, approval: PendingApproval) -> None:
        try:
            conn = self._connect()
            conn.execute(
                "INSERT OR REPLACE INTO pending_approval "
                "(id, amount, description, reason, created_at) "
                "VALUES (1, ?, ?, ?, ?)",
                (approval.amount, approval.description,
                 approval.reason, approval.created_at),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise StorageError(f"failed to set pending approval: {e}") from e

    def clear_pending_approval(self) -> None:
        try:
            conn = self._connect()
            conn.execute("DELETE FROM pending_approval WHERE id = 1")
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise StorageError(f"failed to clear pending approval: {e}") from e

    def get_kill_switch(self) -> KillSwitchState:
        try:
            conn = self._connect()
            row = conn.execute("SELECT * FROM kill_switch WHERE id = 1").fetchone()
            conn.close()
            if row is None:
                return KillSwitchState()
            return KillSwitchState(
                killed=bool(row["killed"]),
                reason=row["reason"],
                by=row["by"],
                changed_at=row["changed_at"],
            )
        except sqlite3.Error as e:
            raise StorageError(f"failed to get kill switch state: {e}") from e

    def set_kill_switch(self, state: KillSwitchState) -> None:
        try:
            conn = self._connect()
            conn.execute(
                "INSERT OR REPLACE INTO kill_switch "
                "(id, killed, reason, by, changed_at) VALUES (1, ?, ?, ?, ?)",
                (int(state.killed), state.reason, state.by, state.changed_at),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as e:
            raise StorageError(f"failed to set kill switch state: {e}") from e
