"""Guard enablement gate — the single source of truth for which harness
guards are active.

Every surface (the ``custodian guards`` CLI, ``install-custodian.py``,
the Hermes plugin, future dotfiles) reads and writes this ONE state file,
so "enabled" can never disagree between Hermes and the terminal.

Guards are dormant by default: installing custodian-kernel activates
nothing. ``custodian guards enable <name>`` is the only path that flips a
guard on, and ``custodian guards status`` is the auditable record.

Concurrency / safety properties (post-Codex sign-off):
- Atomic write via per-write unique temp file + os.replace (no torn reads).
- fsync before replace so a crash does not leave the previous state lost.
- Inter-process lock (POSIX fcntl + Windows msvcrt fallback) so two writers
  cannot clobber each other.
- Symlink-safe state directory: reject if the state file or its temp dir
  parent resolves through a symlink we did not create, or if the directory
  has unsafe permissions (we created it ourselves, so this is enforced).
- Schema validation on load: any file that is valid JSON but the wrong
  shape falls back to the dormant baseline rather than crashing.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

GUARD_NAMES = ("codex", "claude", "hermes")
_STATE_FILENAME = "guards.json"
_STATE_VERSION = 1


def default_state_dir() -> str:
    return os.environ.get("CUSTODIAN_STATE_DIR", str(Path.home() / ".custodian"))


def state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / _STATE_FILENAME


def _dormant() -> dict:
    return {"version": _STATE_VERSION, "guards": {}}


def _fail_closed() -> dict:
    """Sentinel state: corrupt/unreadable state with no valid backup.

    Hooks check :func:`is_fail_closed` before anything else and DENY every
    action — the opposite of ``_dormant()`` (which defers). A guard that
    cannot read its own state must not silently disarm itself.
    """
    return {"version": _STATE_VERSION, "_fail_closed": True, "guards": {}}


def is_fail_closed(state_dir: str | Path) -> bool:
    """True when the gate state is corrupt with no valid backup.

    The guard layer treats this as a hard deny-all (like the kill switch)
    until the operator repairs the state file. Hooks check this FIRST.
    """
    return bool(load_state(state_dir).get("_fail_closed"))


def _validate_shape(data: dict) -> bool:
    """Return True if ``data`` is the expected gate-state shape.

    We only accept a top-level dict with ``version`` int and a ``guards``
    dict. Any other shape (valid JSON, wrong form) is treated as no state.
    """
    if not isinstance(data, dict):
        return False
    if not isinstance(data.get("version"), int):
        return False
    guards = data.get("guards")
    if not isinstance(guards, dict):
        return False
    for rec in guards.values():
        if not isinstance(rec, dict):
            return False
        if "enabled" in rec and not isinstance(rec["enabled"], bool):
            return False
    return True


def _has_symlink_ancestor(p: Path) -> bool:
    """True when any ancestor of ``p`` (including its parent) is a symlink.

    The final component is checked separately by callers; this walks the
    directory chain so an attacker cannot redirect the state dir by
    symlinking an ancestor (e.g. ``~`` or ``~/.custodian``'s parent).
    """
    cur = p.parent
    while cur != cur.parent:
        if cur.is_symlink():
            return True
        cur = cur.parent
    return False


def _unsafe_state_dir_mode(state_dir: str | Path) -> bool:
    """True when the state directory is group/world-writable.

    A group/world-writable state dir means another local user could swap
    the state file (enable/disable guards at will). The launcher creates
    the dir with 0700; anything looser is refused like a symlink.
    """
    try:
        mode = stat.S_IMODE(Path(state_dir).stat().st_mode)
    except OSError:
        return False
    return bool(mode & 0o022)


def load_state(state_dir: str | Path) -> dict:
    p = state_path(state_dir)
    # Read-side symlink integrity, mirroring _write_state: a symlinked
    # state directory or state file means the file we read is not the
    # one the kernel wrote. Treat it like corruption — loud warning,
    # dormant fallback — never silently trust a symlink's content.
    if _has_symlink_ancestor(p) or p.is_symlink():
        print(
            f"custodian: FATAL — gate state path {p} is (or is under) a symlink; "
            f"FAILING CLOSED — all guards deny until the symlink is removed. "
            f"Remove the symlink and re-run 'custodian guards enable <name>'.",
            file=sys.stderr,
        )
        return _fail_closed()
    if _unsafe_state_dir_mode(state_dir):
        print(
            f"custodian: FATAL — gate state dir {state_dir} is group/world "
            f"writable; FAILING CLOSED — all guards deny until the mode is "
            f"fixed. chmod 700 and re-run 'custodian guards enable <name>'.",
            file=sys.stderr,
        )
        return _fail_closed()
    if not p.is_file():
        return _dormant()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        # Loud, not silent: a corrupt state file means we cannot know the
        # operator's intent. Preserve the LAST-KNOWN-GOOD state from the
        # .bak if one exists; otherwise FAIL CLOSED (deny) instead of
        # silently disarming guards the operator enabled.
        bak = Path(str(p) + ".bak")
        if bak.is_file():
            try:
                data = json.loads(bak.read_text(encoding="utf-8"))
                if _validate_shape(data):
                    print(
                        f"custodian: WARNING — gate state file {p} is corrupt "
                        f"({type(exc).__name__}); restored the last-known-good "
                        f"state from {bak.name}. Re-run 'custodian guards "
                        f"status' to confirm.",
                        file=sys.stderr,
                    )
                    return data
            except (ValueError, OSError):
                pass
        print(
            f"custodian: FATAL — gate state file {p} is corrupt "
            f"({type(exc).__name__}) and no valid backup exists; FAILING "
            f"CLOSED — all guards deny until the file is repaired or "
            f"removed. Re-run 'custodian guards enable <name>' to rebuild.",
            file=sys.stderr,
        )
        return _fail_closed()
    if not _validate_shape(data):
        print(
            f"custodian: FATAL — gate state file {p} has an invalid shape; "
            f"FAILING CLOSED — all guards deny until the file is repaired. "
            f"Re-run 'custodian guards enable <name>' to rebuild.",
            file=sys.stderr,
        )
        return _fail_closed()
    return data


# -- file locking -----------------------------------------------------------

class _FileLock:
    """Context manager that takes an advisory exclusive lock on a file.

    POSIX: fcntl.flock. Windows: msvcrt.locking. Falls back to a no-op if
    neither is available — the file is in a per-user directory so the
    race is intra-machine, not adversarial cross-user, and the worst
    case is "two CLI invocations of `custodian guards enable` race";
    the per-write unique temp + replace keeps that from corrupting the
    file even without the lock.
    """
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass  # best-effort; per-write unique temp is the real guard

    def __exit__(self, *exc) -> None:
        if self._fd is None:
            return
        try:
            if sys.platform == "win32":
                try:
                    import msvcrt
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except (ImportError, OSError):
                    pass
            else:
                try:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass
        finally:
            os.close(self._fd)
            self._fd = None


def _write_state(state_dir: str | Path, data: dict) -> None:
    """Atomic, durable, symlink-safe state write.

    - Unique temp file (no fixed name collision).
    - Created in the same directory as the target so os.replace is atomic.
    - fsync of the file and the directory before the replace so the
      update survives a power loss.
    - Resolves any pre-existing symlink at the state path and refuses to
      follow it (defends against an attacker who has placed a symlink in
      ``~/.custodian`` before this user).
    """
    p = state_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    if _has_symlink_ancestor(p) or p.parent.is_symlink():
        # The user's state directory (or an ancestor of it) is a symlink.
        # We refuse to write through it (the launcher's policy is that
        # ~/.custodian is created by us, not linked by the user).
        raise OSError(f"refusing to write gate state through symlinked dir: {p.parent}")
    if p.is_symlink():
        raise OSError(f"refusing to write gate state through existing symlink: {p}")
    fd, tmp_name = tempfile.mkstemp(
        prefix=".guards.", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        # fsync the directory so the temp file's existence is durable too.
        dir_fd = os.open(str(p.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)
        os.replace(tmp_name, p)
        # Preserve the last-known-good state: keep a copy so a torn/corrupt
        # write can be recovered by load_state instead of failing open.
        # Symlink-safe: a preexisting or raced .bak symlink is unlinked
        # (unlink removes the link, never follows it) before the copy.
        try:
            import shutil
            bak = Path(str(p) + ".bak")
            if bak.is_symlink() or bak.exists():
                bak.unlink()
            shutil.copyfile(p, bak)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _validate(name: str) -> None:
    if name not in GUARD_NAMES:
        raise ValueError(
            f"unknown guard {name!r}; choices: {', '.join(GUARD_NAMES)}"
        )


def is_enabled(state_dir: str | Path, name: str) -> bool:
    return bool(load_state(state_dir)["guards"].get(name, {}).get("enabled", False))


def enable(state_dir: str | Path, name: str) -> bool:
    """Return True if the guard was turned on, False if it already was."""
    _validate(name)
    with _FileLock(state_path(state_dir).parent / ".guards.lock"):
        data = load_state(state_dir)
        rec = data["guards"].setdefault(name, {})
        if rec.get("enabled"):
            return False
        rec["enabled"] = True
        rec["updated_at"] = time.time()
        _write_state(state_dir, data)
        return True


def disable(state_dir: str | Path, name: str) -> bool:
    """Return True if the guard was turned off, False if it was already off."""
    _validate(name)
    with _FileLock(state_path(state_dir).parent / ".guards.lock"):
        data = load_state(state_dir)
        rec = data["guards"].get(name)
        if not rec or not rec.get("enabled"):
            return False
        rec["enabled"] = False
        rec["updated_at"] = time.time()
        _write_state(state_dir, data)
        return True


def status_report(state_dir: str | Path) -> list[dict]:
    state = load_state(state_dir)
    return [
        {
            "name": n,
            "enabled": bool(state["guards"].get(n, {}).get("enabled", False)),
            "updated_at": state["guards"].get(n, {}).get("updated_at"),
        }
        for n in GUARD_NAMES
    ]
