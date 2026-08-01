"""Vendor-neutral file-ledger primitives shared by the authority-gate paths.

Extracted verbatim from skills/payments/stripe-spend/scripts/_core.py (and its
bundled copy) so the kernel owns one canonical implementation of the atomic
file write, the OS advisory file lock, and the JSONL audit append instead of
two drifting copies. Each helper takes its paths as arguments — no module-level
state, no network, no sandbox assumptions.
"""
import contextlib
import json
import os
import random
import time
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """Write content atomically: write to random-named temp file, then rename.

    os.replace on the same filesystem is atomic, and unlike os.rename it also
    replaces an existing target on Windows rather than raising FileExistsError.

    fsync's fd must come from the SAME file object the whole way through (via
    a `with` block). A previous version called
    `os.fsync(tmp_path.open("rb").fileno())`, whose anonymous file object has
    no reference held once .fileno() returns, so CPython's refcounting GC
    closes it immediately and hands fsync an already-closed fd -- reproducible
    as OSError: [Errno 9] Bad file descriptor. Because _atomic_write is the
    last step of save_state(), and save_state() runs AFTER the charge, this
    raised on every successful spend: money moved, budget never decremented,
    no audit entry written. notify.py fixed this and documented it; the fix
    was never propagated here.
    """
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    tmp_name = str(path) + f".tmp.{os.getpid()}.{random.randint(100000, 999999)}"
    tmp_path = Path(tmp_name)
    try:
        with open(tmp_path, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# -- cross-process state lock -------------------------------------------------
#
# The spend path is a read-modify-write on spent_this_session across a slow
# network call, which is a classic TOCTOU: two concurrent spends both loaded
# spent=$0 before either wrote, both charged, and the second save clobbered the
# first's increment -- $1000 charged, $250 recorded, and the kernel then
# believed it still had budget it had already spent. An OS advisory lock makes
# the check-and-reserve atomic; the charge itself stays OUTSIDE the lock so
# network latency never serializes unrelated spends.
try:  # POSIX
    import fcntl

    def lock_fd(fd):
        fcntl.flock(fd, fcntl.LOCK_EX)

    def unlock_fd(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)
except ImportError:  # Windows
    import msvcrt

    def lock_fd(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def unlock_fd(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def state_lock(lock_dir: Path):
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / ".state.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        lock_fd(fd)
        try:
            yield
        finally:
            unlock_fd(fd)
    finally:
        os.close(fd)


def append_log(log_file: Path, record: dict) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record["ts"] = time.time()
    record["iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(log_file, "a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()
        os.fsync(f.fileno())
