"""Value-free, HMAC hash-chained receipts for Codex Guard decisions."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any

GENESIS = "0" * 64


class ReceiptChain:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.path = state_dir / "codex-guard-receipts.jsonl"
        self.key_path = state_dir / "codex-guard.key"
        self._lock = Lock()

    def _key(self) -> bytes:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(os.urandom(32))
        key = self.key_path.read_bytes()
        if len(key) != 32:
            raise ValueError("receipt key is invalid")
        return key

    @staticmethod
    def _canonical(value: dict[str, Any]) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def append(self, decision: dict[str, Any], *, tool: str, session_id: str) -> dict[str, Any]:
        # Deliberately value-free: arguments and model text never enter receipts.
        with self._lock:
            records = self._records()
            prev = records[-1]["mac"] if records else GENESIS
            body = {
                "ts": time.time(),
                "event": "codex_guard_decision",
                "tool": tool[:128],
                "session_id": session_id[:128],
                "verdict": decision["verdict"],
                "action_kind": decision["action_kind"],
                "band": decision["band"],
                "reason": decision["reason"][:512],
            }
            mac = hmac.new(self._key(), prev.encode() + self._canonical(body), hashlib.sha256).hexdigest()
            record = {**body, "prev": prev, "mac": mac}
            self.state_dir.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return record

    def verify(self) -> int:
        prev = GENESIS
        key = self._key()
        records = self._records()
        for index, record in enumerate(records):
            if record.get("prev") != prev:
                raise ValueError(f"receipt {index}: broken previous-record link")
            body = {k: record[k] for k in (
                "ts", "event", "tool", "session_id", "verdict",
                "action_kind", "band", "reason",
            )}
            expected = hmac.new(key, prev.encode() + self._canonical(body), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, record.get("mac", "")):
                raise ValueError(f"receipt {index}: HMAC mismatch")
            prev = record["mac"]
        return len(records)
