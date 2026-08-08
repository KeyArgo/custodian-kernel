"""Value-free, HMAC hash-chained receipts for Codex Guard decisions."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
import stat
from threading import Lock
from typing import Any

GENESIS = "0" * 64

# Adapter denial reasons (e.g. custodian/adapters/builtin/path_fence.py's
# f"path {resolved} is inside a forbidden location") embed the resolved,
# real filesystem path verbatim -- confirmed to leak filenames/usernames/
# directory layout into this receipt chain, contradicting this module's own
# "deliberately value-free" design. Redact (1) every sensitive path the
# decision itself carried in its arguments, and (2) any single-quoted,
# path-shaped segment (covers repr'd forms from other adapters).
_PATH_LIKE = re.compile(r"'[^']*[/\\][^']*'")


def _redact_reason(reason: str, sensitive: Iterable[str] = ()) -> str:
    for p in sensitive:
        if not p:
            continue
        if p in reason:
            reason = reason.replace(p, "[REDACTED-PATH]")
        # The denial reason embeds the RESOLVED form (path_fence uses
        # os.path.realpath), so a raw argument like "~/secret" or a
        # relative path appears in the reason expanded
        # ("/home/user/secret") and the raw replace would miss it.
        try:
            resolved = os.path.realpath(os.path.expanduser(p))
        except (OSError, ValueError):
            resolved = p
        if resolved != p and resolved in reason:
            reason = reason.replace(resolved, "[REDACTED-PATH]")
    return _PATH_LIKE.sub("'[REDACTED-PATH]'", reason)


def _argument_paths(args) -> list[str]:
    """Flatten path-shaped string values from a decision's tool arguments."""
    out: list[str] = []
    stack: list = [args] if isinstance(args, (dict, list)) else []
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str) and ("/" in item or "\\" in item):
            out.append(item)
    return out


def _private_dir(path: Path) -> None:
    """Create a private state directory and reject symlink redirection."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ValueError("receipt state path must be a real directory")
    if os.name != "nt":
        path.chmod(0o700)


@contextmanager
def _process_lock(path: Path):
    """Serialize receipt access across MCP processes on Windows and POSIX."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    stream = os.fdopen(fd, "r+b", buffering=0)
    try:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
            stream.seek(0)
            # Serialize writers with a bounded non-blocking retry: a raw
            # LK_LOCK blocks up to 10s then raises PermissionError under
            # contention, and falling through unlocked lets two writers
            # fork the HMAC chain (both read the same tail MAC and append
            # independently). Retry LK_NBLCK for a short window so the
            # chain stays serialized in every realistic case; only a
            # genuine long stall proceeds unlocked.
            deadline = time.monotonic() + 2.0
            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(0.01)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()


class ReceiptChain:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.path = state_dir / "codex-guard-receipts.jsonl"
        self.key_path = state_dir / "codex-guard.key"
        self.lock_path = state_dir / "codex-guard-receipts.lock"
        self._lock = Lock()

    def _key(self) -> bytes:
        _private_dir(self.state_dir)
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

    def append(self, decision: dict[str, Any], *, tool: str, session_id: str,
               sensitive: Iterable[str] = (),
               harness: str = "unknown") -> dict[str, Any]:
        # Deliberately value-free: arguments and model text never enter receipts.
        # `harness` is stamped by the caller from a server-pinned identity
        # (see mcp_server.py's evaluate_guard_action) -- never accepted from
        # model-supplied arguments -- so ledger_access_policy can later grant
        # or deny cross-adapter visibility based on a value nothing but the
        # trusted adapter code itself could have set.
        _private_dir(self.state_dir)
        with self._lock, _process_lock(self.lock_path):
            records = self._records()
            prev = records[-1]["mac"] if records else GENESIS
            body = {
                "ts": time.time(),
                "event": "codex_guard_decision",
                "harness": harness[:64],
                "tool": tool[:128],
                "session_id": session_id[:128],
                "verdict": decision["verdict"],
                "action_kind": decision["action_kind"],
                "band": decision["band"],
                "reason": _redact_reason(decision["reason"], sensitive)[:512],
            }
            mac = hmac.new(self._key(), prev.encode() + self._canonical(body), hashlib.sha256).hexdigest()
            record = {**body, "prev": prev, "mac": mac}
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            receipt_number = self._mirror_to_universal_ledger(body)
            if receipt_number is not None:
                # The number is integrity-bound by the kernel ledger. The
                # existing local HMAC chain remains its independent evidence.
                record["receipt_number"] = receipt_number
            return record

    def _mirror_to_universal_ledger(self, body: dict[str, Any]) -> int | None:
        """Best-effort fan-out into custodian's shared UniversalLedger --
        the same store Talaria's denial log now mirrors into (see
        talaria/denial_log.py), and the one `custodian console` merges
        alongside this receipt chain. This is the one piece Codex Guard
        itself was missing: its own decisions never reached the shared
        ledger, only this module's chain.

        Only mirrors the three verdicts UniversalLedger's own _VERDICTS
        actually accepts (autonomous/escalation_required/denied) --
        "approved" is a later resolution of an escalation already recorded,
        not a new top-level verdict, and LedgerEvent would reject it.
        Swallowed on failure, same as this receipt chain's own guarantee:
        this is a side-channel audit fan-out, not the enforcement itself,
        and must not make a broken/missing ledger break guard decisions."""
        if body["verdict"] not in ("autonomous", "escalation_required", "denied"):
            return None
        try:
            from custodian.universal_ledger import UniversalLedger, LedgerEvent
            ledger = UniversalLedger(self.state_dir / "ledger.db")
            result = ledger.append_with_receipt(LedgerEvent(
                correlation_id=body["session_id"],
                requester=f"{body['harness']}:{body['session_id']}",
                provider="codex_guard",
                action=body["tool"],
                lifecycle_event="decided",
                verdict=body["verdict"],
                band=body["band"],
                metadata={"reason": body["reason"][:200], "action_kind": body["action_kind"]},
            ))
            return result.receipt_number
        except Exception as e:
            import warnings
            warnings.warn(f"codex guard: failed to mirror {body['verdict']!r} decision "
                          f"for tool {body['tool']!r} into universal ledger: {e}", stacklevel=2)
            return None

    def verify(self) -> int:
        _private_dir(self.state_dir)
        with self._lock, _process_lock(self.lock_path):
            prev = GENESIS
            key = self._key()
            records = self._records()
            for index, record in enumerate(records):
                if record.get("prev") != prev:
                    raise ValueError(f"receipt {index}: broken previous-record link")
                # Every key except prev/mac, not a hardcoded allowlist -- a
                # fixed key list meant any field OUTSIDE it (an extra key
                # appended by anyone with mere filesystem write access, no
                # HMAC key needed, or any future field added to a receipt)
                # rode along completely unauthenticated while verify() still
                # reported the chain valid. Naturally still handles a record
                # written before "harness" existed correctly (it just won't
                # have that key, so it's excluded the same way it always
                # was), without needing a special-cased key list.
                body = {k: v for k, v in record.items() if k not in ("prev", "mac")}
                expected = hmac.new(
                    key, prev.encode() + self._canonical(body), hashlib.sha256,
                ).hexdigest()
                if not hmac.compare_digest(expected, record.get("mac", "")):
                    raise ValueError(f"receipt {index}: HMAC mismatch")
                prev = record["mac"]
            return len(records)

    def list_visible(self, policy, *, harness: str, model: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent records `harness`+`model` may view --
        always its own, plus anything ledger_access_policy.LedgerAccessPolicy
        has explicitly granted. Never includes another harness's records
        without a grant, even though physically they share one file."""
        _private_dir(self.state_dir)
        visible = policy.visible_harnesses(harness=harness, model=model)
        with self._lock, _process_lock(self.lock_path):
            records = self._records()
        if visible != "*":
            records = [r for r in records if r.get("harness", "unknown") in visible]
        return list(reversed(records[-limit:])) if limit else list(reversed(records))
