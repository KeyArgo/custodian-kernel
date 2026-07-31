"""Granular, scoped gate policy for harness actions.

The policy is intentionally value-free. Rules match normalized metadata and
never persist tool arguments or credential values.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
import fnmatch
import json
import os
from pathlib import Path
import time
import threading
from uuid import uuid4

from custodian.control.policy import _lock_fd, _unlock_fd
from custodian.control.settings import ControlSettingsStore


GATES = frozenset({
    "filesystem_read", "filesystem_write", "outside_workspace", "shell",
    "network", "credentials", "package_install", "destructive", "git_write",
    "production", "money", "governance",
})
MODES = frozenset({"allow", "ask", "block"})
SCOPES = frozenset({"action", "session", "project", "path", "global"})
ASK_BY_DEFAULT = frozenset({
    "network", "credentials", "destructive", "git_write", "production", "money",
    "governance",
})


@dataclass(frozen=True)
class GateContext:
    gate: str
    harness: str
    tool: str
    session_id: str
    project: str
    path: str = ""
    action_digest: str = ""


@dataclass(frozen=True)
class GateRule:
    gate: str
    mode: str
    scope: str = "global"
    target: str = "*"
    harness: str = "*"
    tool: str = "*"
    expires_at: float | None = None
    rule_id: str = field(default_factory=lambda: str(uuid4()))

    def validate(self) -> None:
        if self.gate not in GATES and self.gate != "*":
            raise ValueError(f"unknown gate: {self.gate}")
        if self.mode not in MODES:
            raise ValueError("mode must be allow, ask, or block")
        if self.scope not in SCOPES:
            raise ValueError(f"unknown scope: {self.scope}")
        if not self.target:
            raise ValueError("scope target is required")

    def matches(self, context: GateContext, now: float) -> bool:
        if self.expires_at is not None and now > self.expires_at:
            return False
        if self.gate not in {"*", context.gate}:
            return False
        if not fnmatch.fnmatchcase(context.harness, self.harness):
            return False
        if not fnmatch.fnmatchcase(context.tool, self.tool):
            return False
        values = {
            "action": context.action_digest,
            "session": context.session_id,
            "project": context.project,
            "path": context.path,
            "global": "*",
        }
        value = values[self.scope]
        if self.scope == "path":
            try:
                value = str(Path(value).expanduser().resolve())
                target = str(Path(self.target).expanduser().resolve())
                return value == target or value.startswith(target + os.sep)
            except (OSError, RuntimeError, ValueError):
                return False
        return fnmatch.fnmatchcase(value, self.target)


class GatePolicy:
    """Last matching rule at the most specific scope wins."""

    _SPECIFICITY = {"global": 0, "project": 1, "path": 2, "session": 3, "action": 4}

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._thread_lock = threading.Lock()

    @contextmanager
    def _lock(self):
        with self._thread_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(
                self.path.parent / (self.path.name + ".lock"),
                os.O_RDWR | os.O_CREAT,
                0o600,
            )
            try:
                _lock_fd(fd)
                yield
            finally:
                _unlock_fd(fd)
                os.close(fd)

    def _load(self) -> list[GateRule]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError
            rules = [GateRule(**item) for item in data]
            for rule in rules:
                rule.validate()
            return rules
        except FileNotFoundError:
            return []

    def list(self) -> list[GateRule]:
        with self._lock():
            return self._load()

    def _save(self, rules: list[GateRule]) -> None:
        for rule in rules:
            rule.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(f".{uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump([asdict(rule) for rule in rules], stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def save(self, rules: list[GateRule]) -> None:
        with self._lock():
            self._save(rules)

    def add(self, rule: GateRule) -> None:
        with self._lock():
            rules = self._load()
            rules.append(rule)
            self._save(rules)

    def decide(self, context: GateContext) -> tuple[str, str, str]:
        matches = [
            (self._SPECIFICITY[rule.scope], index, rule)
            for index, rule in enumerate(self.list())
            if rule.matches(context, time.time())
        ]
        if matches:
            rule = max(matches, key=lambda item: (item[0], item[1]))[2]
            return rule.mode, rule.rule_id, rule.scope
        settings = ControlSettingsStore(
            self.path.parent / "control-settings.json"
        ).load()
        mode = (
            "ask"
            if settings.enforcement_for(context.harness) == "protected"
            and context.gate in ASK_BY_DEFAULT
            else "allow"
        )
        return mode, f"default:{context.gate}", "global"
