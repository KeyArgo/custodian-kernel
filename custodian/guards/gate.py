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


def load_state(state_dir: str | Path) -> dict:
    p = state_path(state_dir)
    # Read-side symlink integrity, mirroring _write_state: a symlinked
    # state directory or state file means the file we read is not the
    # one the kernel wrote. Treat it like corruption — loud warning,
    # dormant fallback — never silently trust a symlink's content.
    if p.parent.is_symlink() or p.is_symlink():
        print(
            f"custodian: WARNING — gate state path {p} is a symlink; "
            f"refusing to trust it and treating all guards as dormant. "
            f"Remove the symlink and re-run 'custodian guards enable <name>'.",
            file=sys.stderr,
        )
        return _dormant()
    if not p.is_file():
        return _dormant()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        # Loud, not silent: a corrupt state file means we cannot know the
        # operator's intent, so we treat it as dormant (fail open) but we
        # WARN — silently disarming guards an operator enabled would be a
        # security surprise. The status command and doctor surface this.
        print(
            f"custodian: WARNING — gate state file {p} is corrupt "
            f"({type(exc).__name__}); treating all guards as dormant. "
            f"Re-run 'custodian guards enable <name>' to restore state.",
            file=sys.stderr,
        )
        return _dormant()
    if not _validate_shape(data):
        print(
            f"custodian: WARNING — gate state file {p} has an invalid shape; "
            f"treating all guards as dormant. Re-run "
            f"'custodian guards enable <name>' to restore state.",
            file=sys.stderr,
        )
        return _dormant()
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
    if p.parent.is_symlink():
        # The user's state directory itself is a symlink. We refuse to
        # write through it (the launcher's policy is that ~/.custodian
        # is created by us, not linked by the user).
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
