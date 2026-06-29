"""Append-only audit log.

Same on-disk format the proven _core.append_log() already writes
(state/audit_log.jsonl, one JSON object per line, ts + iso fields added at
write time) — this module formalizes that format with read/query support,
it does not change it.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterator, Optional

from custodian.exceptions import AuditWriteError
from custodian.types import AuditEntry


class AuditLog:
    def __init__(self, path: Path):
        self.path = path

    def append(self, entry: AuditEntry) -> None:
        record = entry.to_dict()
        record.setdefault("ts", time.time())
        record.setdefault("iso", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record["ts"])))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Append in binary mode with an explicit flush+fsync so a crash
            # immediately after write can't leave a half-written line —
            # the audit log is the thing we ask people to trust, it has to
            # survive being yanked mid-write.
            line = (json.dumps(record) + "\n").encode("utf-8")
            with open(self.path, "ab") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise AuditWriteError(f"failed to write audit log at {self.path}: {e}") from e

    def read_all(self) -> Iterator[AuditEntry]:
        if not self.path.exists():
            return
        with open(self.path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield AuditEntry.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError):
                    continue

    def tail(self, limit: int = 50) -> list[AuditEntry]:
        entries = list(self.read_all())
        return entries[-limit:][::-1]

    def filter_by_event(self, event: str) -> list[AuditEntry]:
        return [e for e in self.read_all() if e.event == event]

    def total_spent(self, *, autonomous_only: bool = False, approved_only: bool = False) -> float:
        total = 0.0
        for e in self.read_all():
            if e.event != "executed":
                continue
            if autonomous_only and e.approved_by:
                continue
            if approved_only and not e.approved_by:
                continue
            total += e.amount
        return round(total, 2)
