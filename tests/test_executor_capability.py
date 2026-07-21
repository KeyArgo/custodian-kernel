"""Tests for the delegated executor's capability primitive: signed,
digest-bound, single-use, TTL-bound approval records."""
import threading
import time

import pytest

from custodian.executor.capability import (
    CapabilityError,
    CapabilityStore,
    action_digest,
)


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

    # Flip a field directly on disk without re-sealing the MAC -- e.g. an
    # attacker with filesystem access trying to rewrite who approved this.
    import json
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

    # A different requester's identical action must not find someone else's.
    assert store.find_pending_by_digest(digest, "someone-else") is None


def test_find_pending_by_digest_ignores_consumed_capabilities(tmp_path):
    store = CapabilityStore(tmp_path)
    digest = action_digest(tool="t", args={}, workspace="/ws", requester="r")
    cap = store.request(digest=digest, requester="r")
    store.approve(cap.capability_id, approved_by="op")
    store.consume(cap.capability_id, digest=digest, requester="r")

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
