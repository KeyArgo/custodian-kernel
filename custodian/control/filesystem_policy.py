"""Per-harness/model read and write scopes; explicit deny always wins.

Cross-process writes use fcntl.flock for atomic read-modify-write.
Paths are canonicalized via os.path.realpath before enforcement.
Malformed state fails closed — corrupt data yields a deny-all fence.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from custodian.adapters.builtin._paths import resolve as canonicalize


def _lock_fd(fd: int) -> None:
    """Serialize policy access across processes on POSIX and Windows."""
    if os.name == "nt":
        import msvcrt
        if os.fstat(fd).st_size == 0:
            os.write(fd, b" ")
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
class FilesystemRule:
    harness: str
    access: str
    model: str = "*"
    allow_roots: tuple[str, ...] = ()
    deny_roots: tuple[str, ...] = ()
    enforcement: str = "routed"
    rule_id: str = field(default_factory=lambda: str(uuid4()))

    def validate(self) -> None:
        if not self.harness or self.harness == "*":
            raise ValueError("filesystem rules require a specific harness")
        if self.access not in {"read", "write"}:
            raise ValueError("access must be read or write")
        if self.enforcement not in {"routed", "brokered"}:
            raise ValueError("enforcement must be routed or brokered")
        if not self.allow_roots and not self.deny_roots:
            raise ValueError("at least one allow or deny root is required")
        if any(not isinstance(root, str) or not root.strip()
               for root in (*self.allow_roots, *self.deny_roots)):
            raise ValueError("filesystem roots must be non-empty strings")

    def _canonical_roots(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        allow = tuple(canonicalize(p) for p in self.allow_roots)
        deny = tuple(canonicalize(p) for p in self.deny_roots)
        filtered_allow = tuple(
            a for a in allow
            if not any(a == d or a.startswith(d + os.sep) for d in deny)
        )
        return filtered_allow, deny


class FilesystemPolicy:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        # A lock bound to the DATA file's own fd stops being valid the
        # instant that file gets atomically replaced (os.replace() swaps
        # the directory entry to a new inode; flock()/LockFileEx() bind to
        # the open file description, not the pathname -- any holder of the
        # old, now-orphaned fd is no longer serialized against a fresh
        # opener of the new one). A separate, never-replaced lock file
        # (same pattern as codex_guard/approvals.py and control/policy.py)
        # keeps the SAME inode locked across every writer regardless of how
        # many times the data file itself gets swapped out from under it.
        self.lock_path = self.path.parent / (self.path.name + ".lock")

    # -- locked read / write primitives ---------------------------------------

    def _read_data_file(self) -> list[FilesystemRule]:
        try:
            raw_text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        if not raw_text.strip():
            return []
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            raise ValueError("filesystem policy is malformed; access denied")
        if not isinstance(data, list):
            raise ValueError("filesystem policy must be a list")
        rules = [
            FilesystemRule(**{
                **item,
                "allow_roots": tuple(item.get("allow_roots", ())),
                "deny_roots": tuple(item.get("deny_roots", ())),
            })
            for item in data
        ]
        for rule in rules:
            rule.validate()
        return rules

    def _write_data_file(self, rules: list[FilesystemRule]) -> None:
        for rule in rules:
            rule.validate()
        # Write-to-temp + os.replace instead of truncating the live file in
        # place. A crash between truncate and write left a 0-byte file, and
        # a 0-byte file is treated as "valid, no rules" (see
        # _read_data_file's empty-string branch), not as malformed --
        # silently reverting every scoped rule (including a deny-root for
        # something like ~/.ssh) to whatever permissive default the caller
        # passes, instead of failing closed.
        tmp = self.path.with_suffix(f".{uuid4().hex}.tmp")
        tmp_fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as stream:
                json.dump([asdict(r) for r in rules], stream, sort_keys=True, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _with_lock(self, body):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock_fd(lock_fd)
            return body()
        finally:
            _unlock_fd(lock_fd)
            os.close(lock_fd)

    def _read_modify_write(self, mutator):
        def _body():
            rules = self._read_data_file()
            mutator(rules)
            self._write_data_file(rules)
        self._with_lock(_body)

    # -- public API -----------------------------------------------------------

    def list(self) -> list[FilesystemRule]:
        return self._with_lock(self._read_data_file)

    def add(self, rule: FilesystemRule) -> None:
        rule.validate()
        self._read_modify_write(lambda rules: rules.append(rule))

    def remove(self, rule_id: str) -> bool:
        removed = False
        def _remove(rules):
            nonlocal removed
            before = len(rules)
            rules[:] = [r for r in rules if r.rule_id != rule_id]
            removed = len(rules) < before
        self._read_modify_write(_remove)
        return removed

    def effective(self, *, harness: str, model: str, access: str) -> FilesystemRule | None:
        matches = [
            r for r in self.list()
            if r.harness == harness and r.access == access and r.model in {"*", model}
        ]
        exact = [r for r in matches if r.model == model]
        return (exact or matches)[-1] if matches else None

    def fence_config(self, *, harness: str, model: str, access: str,
                     inherited_allow: list[str], inherited_deny: list[str]) -> dict:
        # The whole body is covered, not just self.effective(...) -- a
        # malformed stored root (e.g. an embedded null byte) doesn't raise
        # until _canonical_roots()/canonicalize() actually resolve it, which
        # used to happen OUTSIDE this try/except and crash uncaught instead
        # of returning the documented deny-all fence below. A well-formed
        # policy file containing just one bad value violated this method's
        # own stated fail-closed contract.
        try:
            rule = self.effective(harness=harness, model=model, access=access)
            if rule is None:
                return {
                    "allow_paths": [canonicalize(p) for p in inherited_allow],
                    "forbidden_paths": [canonicalize(p) for p in inherited_deny],
                    "source": "harness-default",
                    "enforcement": "routed",
                }
            canonical_allow, canonical_deny = rule._canonical_roots()
            all_forbidden = [canonicalize(p) for p in inherited_deny]
            all_forbidden.extend(canonical_deny)
            return {
                "allow_paths": list(canonical_allow),
                "forbidden_paths": all_forbidden,
                "source": rule.rule_id,
                "enforcement": rule.enforcement,
            }
        except ValueError:
            return {
                "allow_paths": [],
                "forbidden_paths": ["/"],
                "source": "malformed-policy",
                "enforcement": "routed",
            }
