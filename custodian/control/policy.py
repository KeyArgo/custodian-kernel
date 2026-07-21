"""Deterministic, scoped approval rules shared by all adapters."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import fnmatch
import json
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

NEVER_AUTO = frozenset({"governance", "credential", "destructive", "production", "money"})
MODES = frozenset({"deny", "ask", "auto"})


def _lock_fd(fd: int) -> None:
    """Take an exclusive cross-process lock on POSIX and Windows."""
    if os.name == "nt":
        import msvcrt
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


@dataclass(frozen=True)
class Proposal:
    adapter: str
    action_kind: str
    tool: str
    requester: str
    workspace: str = ""
    host: str = ""
    amount: float | None = None


@dataclass(frozen=True)
class ApprovalRule:
    rule_id: str = field(default_factory=lambda: str(uuid4()))
    mode: str = "ask"
    adapter: str = "*"
    action_kind: str = "*"
    tool: str = "*"
    requester: str = "*"
    workspace: str = "*"
    host: str = "*"
    max_amount: float | None = None
    expires_at: float | None = None
    max_uses: int | None = None
    uses: int = 0

    def matches(self, proposal: Proposal, now: float) -> bool:
        if self.expires_at is not None and now > self.expires_at:
            return False
        if self.max_uses is not None and self.uses >= self.max_uses:
            return False
        if self.max_amount is not None and (proposal.amount is None or proposal.amount > self.max_amount):
            return False
        return all(fnmatch.fnmatchcase(getattr(proposal, key), getattr(self, key)) for key in
                   ("adapter", "action_kind", "tool", "requester", "workspace", "host"))


class ApprovalPolicy:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._thread_lock = threading.Lock()

    @contextmanager
    def _lock(self):
        with self._thread_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.parent / (self.path.name + ".lock")
            fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC, 0o600)
            try:
                _lock_fd(fd)
                yield
            finally:
                _unlock_fd(fd)
                os.close(fd)

    def _load(self) -> list[ApprovalRule]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            try:
                result.append(ApprovalRule(**item))
            except (TypeError, ValueError):
                continue
        return result

    def _save(self, rules: list[ApprovalRule]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            tmp.unlink(missing_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump([asdict(rule) for rule in rules], stream, sort_keys=True, indent=2)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def add(self, rule: ApprovalRule) -> None:
        if rule.mode not in MODES:
            raise ValueError("mode must be deny, ask, or auto")
        if rule.mode == "auto" and rule.action_kind in NEVER_AUTO:
            raise ValueError(f"{rule.action_kind} actions cannot be auto-approved")
        with self._lock():
            rules = self._load()
            rules.append(rule)
            self._save(rules)

    def remove(self, rule_id: str) -> bool:
        with self._lock():
            rules = self._load()
            kept = [r for r in rules if r.rule_id != rule_id]
            if len(kept) == len(rules):
                return False
            self._save(kept)
            return True

    def list(self) -> list[ApprovalRule]:
        with self._lock():
            return self._load()

    def decide(self, proposal: Proposal) -> tuple[str, str | None]:
        now = time.time()
        with self._lock():
            rules = self._load()
            for index in range(len(rules) - 1, -1, -1):
                rule = rules[index]
                if rule.matches(proposal, now):
                    if rule.mode == "deny":
                        return "deny", rule.rule_id
                    if rule.mode == "auto" and proposal.action_kind in NEVER_AUTO:
                        return "ask", None
                    if rule.mode == "auto":
                        rules[index] = ApprovalRule(**{**asdict(rule), "uses": rule.uses + 1})
                        self._save(rules)
                    return rule.mode, rule.rule_id
        return "ask", None
