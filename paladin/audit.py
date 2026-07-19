"""Hash-chained, HMAC-signed audit log for every broker decision.

Each record carries:

* ``prev`` — the previous record's digest (genesis uses 64 zero chars),
* ``mac``  — HMAC-SHA256 over (prev + canonical record body) under a
  key derived from the vault master key.

Editing, reordering, inserting, or truncating records breaks the chain,
and forging a valid chain requires the vault key. The log itself is
value-free: it records *that* ``skill:stripe-spend`` resolved
``stripe_sk`` at band L2, never any secret material.

``paladin audit verify`` walks the chain and reports the first break.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from paladin.errors import AuditChainBrokenError

GENESIS = "0" * 64


def _canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class AuditRecord:
    ts: float
    event: str          # resolve | deny | grant | revoke | add | delete | rotate
    ref: str            # secret name or pattern ("-" when n/a)
    requester: str
    band: str
    detail: str
    prev: str
    mac: str

    def body(self) -> dict:
        return {
            "ts": self.ts, "event": self.event, "ref": self.ref,
            "requester": self.requester, "band": self.band, "detail": self.detail,
        }


class AuditLog:
    """Append-only JSONL file with an HMAC hash chain."""

    def __init__(self, path: Path, key: bytes) -> None:
        self.path = Path(path)
        self._key = key
        # Serialize append() within a process. The egress gateway drives
        # this from a thread per connection, so concurrent calls would
        # otherwise read the same tail MAC and fork the hash chain (found in
        # review — reproduced with 8 threads). This guards in-process
        # concurrency only; cross-process racing is a separate concern.
        self._lock = threading.Lock()

    def _mac(self, prev: str, body: dict) -> str:
        return hmac.new(self._key, prev.encode() + _canonical(body), hashlib.sha256).hexdigest()

    def _tail_mac(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return GENESIS
        # Read the genuine last line by widening the tail window until it
        # contains a newline before the final line. Records are small, but a
        # long `detail` must never make the chain read a truncated last line
        # and silently start a fresh (breaking) chain.
        with self.path.open("rb") as f:
            size = self.path.stat().st_size
            window = 4096
            while True:
                f.seek(max(0, size - window))
                chunk = f.read()
                lines = chunk.splitlines()
                if window >= size or (len(lines) >= 2):
                    break
                window *= 2
            last = lines[-1]
        return json.loads(last)["mac"]

    def append(self, event: str, ref: str, requester: str, band: str = "L0",
               detail: str = "") -> AuditRecord:
        detail = detail[:512]  # keep records bounded and value-free
        with self._lock:  # read-tail + write must be atomic (see __init__)
            prev = self._tail_mac()
            body = {"ts": time.time(), "event": event, "ref": ref,
                    "requester": requester, "band": band, "detail": detail}
            rec = AuditRecord(**body, prev=prev, mac=self._mac(prev, body))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps({**body, "prev": prev, "mac": rec.mac},
                              sort_keys=True, separators=(",", ":"))
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write(line + "\n")
                f.flush()
                os.fsync(f.fileno())
        return rec

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def verify(self) -> int:
        """Walk the whole chain. Returns the number of valid records, or
        raises AuditChainBrokenError at the first broken link."""
        prev = GENESIS
        for i, rec in enumerate(self.records()):
            body = {k: rec[k] for k in ("ts", "event", "ref", "requester", "band", "detail")}
            if rec.get("prev") != prev:
                raise AuditChainBrokenError(
                    f"record {i}: chain break (expected prev {prev[:12]}…, "
                    f"got {str(rec.get('prev'))[:12]}…)"
                )
            expected = self._mac(prev, body)
            if not hmac.compare_digest(expected, rec.get("mac", "")):
                raise AuditChainBrokenError(f"record {i}: HMAC mismatch — record altered")
            prev = rec["mac"]
        return len(self.records())
