"""Per-harness/model grants controlling cross-adapter ledger/receipt visibility.

Default is self-only: a harness can always see its own receipts/approvals.
Seeing ANOTHER harness's records requires an explicit grant here -- there is
no "deny" rule to write, denial is simply the absence of a grant. This is
deliberately the same shape as FilesystemPolicy (atomic write, cross-process
lock, fail-closed on malformed state) so it reads as one family of policy,
not a bolted-on second convention.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4


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


ALL_HARNESSES = "*"


@dataclass(frozen=True)
class LedgerGrant:
    """Grants `harness` (optionally scoped to one trusted `model`) visibility
    into the ledger/receipt records of every harness named in `can_view`
    (or every harness, if `can_view` contains ALL_HARNESSES)."""
    harness: str
    can_view: tuple[str, ...]
    model: str = "*"
    rule_id: str = field(default_factory=lambda: str(uuid4()))

    def validate(self) -> None:
        if not self.harness or self.harness == ALL_HARNESSES:
            raise ValueError("ledger grants require a specific harness")
        if not self.can_view:
            raise ValueError("can_view must name at least one harness (or '*' for all)")
        if any(not isinstance(h, str) or not h.strip() for h in self.can_view):
            raise ValueError("can_view entries must be non-empty strings")


class LedgerAccessPolicy:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    # -- locked read / write primitives ---------------------------------------

    def _read_under_lock(self, fd: int) -> list[LedgerGrant]:
        size = os.lseek(fd, 0, os.SEEK_END)
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, size) if size > 0 else b""
        raw_text = raw.decode("utf-8")
        if not raw_text.strip():
            return []
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            raise ValueError("ledger access policy is malformed; access denied")
        if not isinstance(data, list):
            raise ValueError("ledger access policy must be a list")
        try:
            grants = [
                LedgerGrant(**{**item, "can_view": tuple(item.get("can_view", ()))})
                for item in data
            ]
            for grant in grants:
                grant.validate()
        except TypeError as exc:
            # A grant entry that's syntactically valid JSON but doesn't
            # match LedgerGrant's constructor (missing the required
            # "harness" field, an unexpected/renamed key from hand-editing
            # or a future schema change) raised an uncaught TypeError here,
            # not the ValueError every caller (visible_harnesses(),
            # cmd_console.py's _draw()) actually catches -- breaking this
            # module's own "fails closed to self-only, never to 'see
            # everything'" guarantee for every harness, not just a
            # malicious one. A single corrupted entry took down
            # cross-harness visibility checking entirely instead of
            # degrading to self-only as documented.
            raise ValueError(f"ledger access policy is malformed; access denied ({exc})")
        return grants

    def _write_under_lock(self, fd: int, grants: list[LedgerGrant]) -> None:
        for grant in grants:
            grant.validate()
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        data = json.dumps([asdict(g) for g in grants], sort_keys=True, indent=2).encode("utf-8")
        os.write(fd, data)
        os.fsync(fd)

    def _read_modify_write(self, mutator):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock_fd(fd)
            grants = self._read_under_lock(fd)
            mutator(grants)
            self._write_under_lock(fd, grants)
        finally:
            _unlock_fd(fd)
            os.close(fd)

    # -- public API -------------------------------------------------------------

    def list(self) -> list[LedgerGrant]:
        try:
            fd = os.open(self.path, os.O_RDONLY)
        except FileNotFoundError:
            return []
        try:
            _lock_fd(fd)
            return self._read_under_lock(fd)
        finally:
            _unlock_fd(fd)
            os.close(fd)

    def add(self, grant: LedgerGrant) -> None:
        grant.validate()
        self._read_modify_write(lambda grants: grants.append(grant))

    def remove(self, rule_id: str) -> bool:
        removed = False
        def _remove(grants):
            nonlocal removed
            before = len(grants)
            grants[:] = [g for g in grants if g.rule_id != rule_id]
            removed = len(grants) < before
        self._read_modify_write(_remove)
        return removed

    # -- decision -----------------------------------------------------------

    def visible_harnesses(self, *, harness: str, model: str) -> frozenset[str] | str:
        """Return the harness identities `harness`+`model` may view, or the
        literal ALL_HARNESSES if granted unrestricted visibility.

        No harness sees anything by default -- not even its own history.
        The agent being governed is exactly the party a hard-denial log
        exists to constrain; letting it read its own reasons/tools/verdicts
        turns the ledger into an oracle it can probe to learn the exact
        enforcement boundary and route around it. Visibility, including a
        harness viewing its own past decisions, is only ever something the
        operator grants explicitly via `custodian console`'s `[G]` key --
        never a starting default. Malformed policy fails closed to nothing
        visible, same direction as every other fail-closed default here."""
        visible = set()
        try:
            grants = self.list()
        except ValueError:
            return frozenset(visible)
        for grant in grants:
            if grant.harness != harness:
                continue
            if grant.model not in (ALL_HARNESSES, model):
                continue
            if ALL_HARNESSES in grant.can_view:
                return ALL_HARNESSES
            visible.update(grant.can_view)
        return frozenset(visible)

    def can_view(self, *, harness: str, model: str, target_harness: str) -> bool:
        visible = self.visible_harnesses(harness=harness, model=model)
        return visible == ALL_HARNESSES or target_harness in visible
