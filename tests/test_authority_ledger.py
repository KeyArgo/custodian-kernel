"""Tests for custodian.authority.ledger — the vendor-neutral file-ledger kernel.

The four primitives were extracted verbatim from the stripe-spend skill's
_core.py so the kernel owns one canonical implementation of the atomic write,
the OS advisory file lock, and the fsynced JSONL audit append. These tests
exercise them directly, independent of the skill.
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from custodian.authority.ledger import (
    append_log,
    atomic_write,
    lock_fd,
    state_lock,
    unlock_fd,
)


# -- atomic_write -------------------------------------------------------------

def test_atomic_write_writes_new_file(tmp_path):
    target = tmp_path / "state" / "x.json"
    atomic_write(target, '{"a": 1}')
    assert json.loads(target.read_text()) == {"a": 1}


def test_atomic_write_replaces_an_existing_file(tmp_path):
    target = tmp_path / "x.json"
    atomic_write(target, '{"v": 1}')
    atomic_write(target, '{"v": 2}')
    assert json.loads(target.read_text()) == {"v": 2}


def test_atomic_write_leaves_no_temp_files_behind(tmp_path):
    target = tmp_path / "x.json"
    atomic_write(target, "{}")
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


# -- lock_fd / unlock_fd ------------------------------------------------------

def test_lock_unlock_fd_do_not_raise_on_current_platform(tmp_path):
    fd = os.open(str(tmp_path / "f.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        lock_fd(fd)
        unlock_fd(fd)
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name == "nt", reason="flock semantics are POSIX-only")
def test_lock_fd_serializes_two_handles(tmp_path):
    """flock locks the open file description, so a second handle must block."""
    path = tmp_path / "f.lock"
    fd1 = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    fd2 = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
    acquired = threading.Event()
    lock_fd(fd1)

    def _second():
        lock_fd(fd2)  # blocks until fd1 is unlocked
        acquired.set()
        unlock_fd(fd2)

    t = threading.Thread(target=_second)
    t.start()
    time.sleep(0.2)  # give the thread time to reach lock_fd and block
    assert not acquired.is_set(), "second handle must block while fd1 holds the lock"
    unlock_fd(fd1)
    t.join(timeout=5)
    assert acquired.is_set(), "second handle must acquire the lock once released"
    os.close(fd1)
    os.close(fd2)


# -- state_lock ---------------------------------------------------------------

def test_state_lock_creates_lock_file_in_the_given_dir(tmp_path):
    lock_dir = tmp_path / "state"
    with state_lock(lock_dir):
        assert (lock_dir / ".state.lock").exists()


def test_state_lock_reentrant_across_sequential_acquisitions(tmp_path):
    with state_lock(tmp_path):
        pass
    with state_lock(tmp_path):  # immediately re-acquirable after release
        pass


@pytest.mark.skipif(os.name == "nt", reason="OS advisory locking semantics are POSIX-only")
def test_state_lock_serializes_concurrent_threads(tmp_path):
    """20 threads each increment once under the lock: no lost updates."""
    counter = {"n": 0}

    def _increment():
        with state_lock(tmp_path):
            current = counter["n"]
            time.sleep(0.001)  # widen the read-modify-write window
            counter["n"] = current + 1

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(lambda _: _increment(), range(20)))

    assert counter["n"] == 20, "every increment must be visible under the lock"


# -- append_log ---------------------------------------------------------------

def test_append_log_adds_ts_and_iso_and_writes_valid_json(tmp_path):
    log = tmp_path / "audit_log.jsonl"
    record = {"event": "executed", "amount": 100.0}
    before = time.time()
    append_log(log, record)
    after = time.time()

    # in-place mutation of the caller's record, exactly as _core.py did
    assert before <= record["ts"] <= after
    assert record["iso"].endswith("Z")

    lines = log.read_text().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event"] == "executed"
    assert parsed["amount"] == 100.0
    assert parsed["ts"] == record["ts"]
    assert parsed["iso"] == record["iso"]


def test_append_log_appends_multiple_flushed_json_lines(tmp_path):
    log = tmp_path / "nested" / "audit_log.jsonl"
    for i in range(3):
        append_log(log, {"event": f"e{i}", "seq": i})
    lines = log.read_text().splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["event"] for line in lines] == ["e0", "e1", "e2"]
