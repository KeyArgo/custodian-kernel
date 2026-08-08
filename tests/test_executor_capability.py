"""Tests for the delegated executor's capability primitive: signed,
digest-bound, single-use, TTL-bound approval records."""
import json
import os
import stat
import threading
import time

import pytest

from custodian.executor.capability import (
    CapabilityError,
    CapabilityStore,
    _path_is_symlink_in_chain,
    action_digest,
)


def test_store_works_when_platform_has_no_o_nofollow(tmp_path, monkeypatch):
    """Windows has no os.O_NOFOLLOW; link/junction checks remain explicit."""
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="read", args={}, workspace="", requester="r")
    record = store.request(digest=digest, requester="r")
    assert store.get(record.capability_id).action_digest == digest


def test_action_digest_is_stable_for_identical_inputs():
    d1 = action_digest(tool="stripe-spend", args={"amount": 5.0}, workspace="/ws", requester="r")
    d2 = action_digest(tool="stripe-spend", args={"amount": 5.0}, workspace="/ws", requester="r")
    assert d1 == d2
    assert len(d1) == 64


@pytest.mark.parametrize("field,value", [
    ("tool", "other-tool"),
    ("args", {"amount": 6.0}),
    ("requester", "someone-else"),
])
def test_action_digest_changes_with_any_bound_field(field, value):
    base = dict(tool="stripe-spend", args={"amount": 5.0}, workspace="/ws", requester="r")
    d1 = action_digest(**base)
    base[field] = value
    d2 = action_digest(**base)
    assert d1 != d2


def test_full_lifecycle_request_approve_consume(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")

    cap = store.request(digest=digest, requester="r")
    assert cap.is_pending

    approved = store.approve(cap.capability_id, approved_by="operator")
    assert approved.is_approved
    assert approved.approved_by == "operator"

    consumed = store.consume(cap.capability_id, digest=digest, requester="r")
    assert consumed.is_consumed


def test_cannot_consume_before_approval(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    with pytest.raises(CapabilityError, match="not been approved"):
        store.consume(cap.capability_id, digest=digest, requester="r")


def test_cannot_consume_twice(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.approve(cap.capability_id, approved_by="op")
    store.consume(cap.capability_id, digest=digest, requester="r")
    with pytest.raises(CapabilityError):
        store.consume(cap.capability_id, digest=digest, requester="r")


def test_approved_capability_cannot_be_applied_to_a_different_action(tmp_path):
    """The exact bypass this exists to close: an operator approves action A,
    the agent tries to consume that approval against action B instead."""
    store = CapabilityStore(tmp_path)
    digest_a = action_digest(tool="refund", args={"amount": 5.0}, workspace="/ws", requester="r")
    digest_b = action_digest(tool="refund", args={"amount": 999999.0}, workspace="/ws", requester="r")

    cap = store.request(digest=digest_a, requester="r")
    store.approve(cap.capability_id, approved_by="operator")

    with pytest.raises(CapabilityError, match="action changed"):
        store.consume(cap.capability_id, digest=digest_b, requester="r")


def test_capability_cannot_be_consumed_by_a_different_requester(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="alice")
    cap = store.request(digest=digest, requester="alice")
    store.approve(cap.capability_id, approved_by="op")
    with pytest.raises(CapabilityError, match="different requester"):
        store.consume(cap.capability_id, digest=digest, requester="mallory")


def test_expired_capability_cannot_be_consumed(tmp_path):
    clock = [1000.0]
    store = CapabilityStore(tmp_path, now=lambda: clock[0])
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r", ttl_seconds=10)
    store.approve(cap.capability_id, approved_by="op")
    clock[0] += 11
    with pytest.raises(CapabilityError, match="expired"):
        store.consume(cap.capability_id, digest=digest, requester="r")


def test_tampering_the_record_on_disk_is_detected(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.approve(cap.capability_id, approved_by="op")

    path = tmp_path / "executor-capabilities" / f"{cap.capability_id}.json"
    record = json.loads(path.read_text())
    assert record["status"] == "approved"
    record["approved_by"] = "not-the-real-operator"
    path.write_text(json.dumps(record))
    with pytest.raises(CapabilityError, match="authentication failed"):
        store.consume(cap.capability_id, digest=digest, requester="r")


def test_find_pending_by_digest_lets_a_retrying_caller_discover_its_own_capability(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")

    found = store.find_pending_by_digest(digest, "r")
    assert found is not None
    assert found.capability_id == cap.capability_id

    assert store.find_pending_by_digest(digest, "someone-else") is None


def test_find_pending_by_digest_ignores_consumed_capabilities(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.approve(cap.capability_id, approved_by="op")
    store.consume(cap.capability_id, digest=digest, requester="r")

    assert store.find_pending_by_digest(digest, "r") is None


def test_find_pending_by_digest_ignores_denied_capabilities(tmp_path):
    """Regression: the docstring promises 'pending/approved' only, but
    "denied" was never actually excluded from the filter -- a resend of the
    identical proposal after an operator's explicit denial kept resolving
    to that same, permanently-denied capability_id (approve() on it fails
    forever with "capability is not pending") instead of a fresh one. The
    action could never be re-escalated again until its original TTL lapsed."""
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.deny(cap.capability_id, denied_by="op")

    assert store.find_pending_by_digest(digest, "r") is None


def test_concurrent_consume_only_one_thread_wins(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.approve(cap.capability_id, approved_by="op")

    wins = []
    errors = []
    lock = threading.Lock()

    def worker():
        try:
            store.consume(cap.capability_id, digest=digest, requester="r")
            with lock:
                wins.append(1)
        except CapabilityError as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(wins) == 1
    assert len(errors) == 19


def test_path_is_symlink_in_chain_detects_direct_symlink(tmp_path):
    target = tmp_path / "real_file"
    target.write_text("data")
    link = tmp_path / "link_file"
    link.symlink_to(target)
    assert _path_is_symlink_in_chain(link) is True


def test_path_is_symlink_in_chain_detects_parent_symlink(tmp_path):
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    child = real_dir / "child.txt"
    child.write_text("data")
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir, target_is_directory=True)
    assert _path_is_symlink_in_chain(link_dir / "child.txt") is True


def test_path_is_symlink_in_chain_returns_false_for_normal_path(tmp_path):
    d = tmp_path / "normal_dir"
    d.mkdir()
    f = d / "normal_file.txt"
    f.write_text("data")
    assert _path_is_symlink_in_chain(f) is False


def test_store_rejects_symlink_key_file(tmp_path):
    real_key = tmp_path / "real_key"
    real_key.write_bytes(b"a" * 32)
    link_key = tmp_path / "executor-capability.key"
    link_key.symlink_to(real_key)
    store = CapabilityStore(tmp_path)
    with pytest.raises(CapabilityError, match="key path compromised"):
        store._key()


def test_store_rejects_symlink_capability_path(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    cap_path = tmp_path / "executor-capabilities" / f"{cap.capability_id}.json"
    real_path = tmp_path / "real_cap.json"
    cap_path.rename(real_path)
    cap_path.symlink_to(real_path)
    with pytest.raises(CapabilityError, match="symlink"):
        store.get(cap.capability_id)


def test_store_rejects_symlink_capabilities_dir(tmp_path):
    real_dir = tmp_path / "real_caps"
    real_dir.mkdir()
    caps_link = tmp_path / "executor-capabilities"
    caps_link.symlink_to(real_dir, target_is_directory=True)
    store = CapabilityStore(tmp_path)
    with pytest.raises(CapabilityError, match="compromised"):
        store.list_records()


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows does not enforce POSIX mode bits (stat() reports "
    "fabricated permissive modes); the 0600/0700 assertions are POSIX-only",
)
def test_permissions_are_set_on_key_and_capability_dir(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")

    dir_mode = stat.S_IMODE(tmp_path.joinpath("executor-capabilities").stat().st_mode)
    assert dir_mode == 0o700

    key_mode = stat.S_IMODE(tmp_path.joinpath("executor-capability.key").stat().st_mode)
    assert key_mode == 0o600

    cap_mode = stat.S_IMODE(
        tmp_path.joinpath("executor-capabilities", f"{cap.capability_id}.json").stat().st_mode
    )
    assert cap_mode == 0o600


def test_consume_claim_file_is_cleaned_up_on_success(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.approve(cap.capability_id, approved_by="op")
    store.consume(cap.capability_id, digest=digest, requester="r")
    claim_path = tmp_path / "executor-capabilities" / f"{cap.capability_id}.claim"
    assert not claim_path.exists()


def test_consume_claim_file_is_cleaned_up_on_failure(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    claim_path = tmp_path / "executor-capabilities" / f"{cap.capability_id}.claim"
    with pytest.raises(CapabilityError, match="not been approved"):
        store.consume(cap.capability_id, digest=digest, requester="r")
    assert not claim_path.exists()


def test_approve_rejects_expired_capability(tmp_path):
    clock = [1000.0]
    store = CapabilityStore(tmp_path, now=lambda: clock[0])
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r", ttl_seconds=10)
    clock[0] += 11
    with pytest.raises(CapabilityError, match="expired"):
        store.approve(cap.capability_id, approved_by="op")


def test_approve_binds_expected_digest(tmp_path):
    store = CapabilityStore(tmp_path)
    digest_a = action_digest(tool="refund", args={"amount": 5.0}, workspace="/ws", requester="r")
    digest_b = action_digest(tool="refund", args={"amount": 999.0}, workspace="/ws", requester="r")
    cap = store.request(digest=digest_a, requester="r")
    with pytest.raises(CapabilityError, match="does not match"):
        store.approve(cap.capability_id, approved_by="op", expected_digest=digest_b)


def test_error_messages_do_not_leak_key_or_path(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.approve(cap.capability_id, approved_by="op")

    cap_path = tmp_path / "executor-capabilities" / f"{cap.capability_id}.json"
    record = json.loads(cap_path.read_text())
    record["mac"] = "bad"
    cap_path.write_text(json.dumps(record))

    with pytest.raises(CapabilityError) as exc:
        store.consume(cap.capability_id, digest=digest, requester="r")
    msg = str(exc.value)
    assert "authentication failed" in msg
    assert tmp_path.as_posix() not in msg
    assert "executor-capability.key" not in msg
    assert cap.capability_id not in msg
