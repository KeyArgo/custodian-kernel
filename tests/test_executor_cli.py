"""Tests for the executor CLI: approve, deny, start, and resolve-capability."""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from custodian.cli.cmd_executor import (
    _default_socket_path,
    _resolve_capability,
    cmd_executor_approve,
    cmd_executor_deny,
    cmd_executor_start,
)
from custodian.executor.capability import CapabilityError, CapabilityStore, action_digest


# ── helpers ──────────────────────────────────────────────────────────────────────

def _make_pending(store: CapabilityStore, *, tool="t", requester="alice") -> str:
    """Create a single pending capability and return its id."""
    digest = action_digest(tool=tool, args={}, workspace="/ws", requester=requester)
    cap = store.request(digest=digest, requester=requester)
    return cap.capability_id


def _make_approved(store: CapabilityStore, *, tool="t", requester="alice") -> str:
    """Create an approved capability and return its id."""
    cap_id = _make_pending(store, tool=tool, requester=requester)
    store.approve(cap_id, approved_by="op")
    return cap_id


def _pending_digest(store: CapabilityStore, cap_id: str) -> str:
    return store.get(cap_id).action_digest


# ── _resolve_capability ──────────────────────────────────────────────────────────

class TestResolveCapability:
    def test_passthrough_exact_id(self, tmp_path):
        store = CapabilityStore(tmp_path)
        assert _resolve_capability(store, "abc-123") == "abc-123"

    def test_latest_resolves_to_most_recent_pending(self, tmp_path):
        clock = iter((1000.0, 1000.1))
        store = CapabilityStore(tmp_path, now=lambda: next(clock))
        id1 = _make_pending(store, tool="a", requester="alice")
        id2 = _make_pending(store, tool="b", requester="alice")
        assert _resolve_capability(store, "latest", now=1000.1) == id2

    def test_latest_ignores_expired(self, tmp_path):
        clock = [1000.0]
        store = CapabilityStore(tmp_path, now=lambda: clock[0])
        _make_pending(store, tool="a", requester="alice")
        clock[0] += 3601  # past max TTL
        with pytest.raises(CapabilityError, match="no unexpired pending"):
            _resolve_capability(store, "latest")

    def test_latest_ignores_approved(self, tmp_path):
        store = CapabilityStore(tmp_path)
        _make_approved(store, tool="a", requester="alice")
        with pytest.raises(CapabilityError, match="no unexpired pending"):
            _resolve_capability(store, "latest")

    def test_latest_empty_store(self, tmp_path):
        store = CapabilityStore(tmp_path)
        with pytest.raises(CapabilityError, match="no unexpired pending"):
            _resolve_capability(store, "latest")

    def test_latest_resolves_fine_with_a_single_requester(self, tmp_path):
        store = CapabilityStore(tmp_path, now=lambda: 1000.0)
        _make_pending(store, tool="a", requester="bob")
        cap_id = _resolve_capability(store, "latest", now=1000.0)
        assert cap_id is not None

    def test_latest_refuses_when_multiple_requesters_are_pending(self, tmp_path):
        """Regression: 'latest' previously scanned every pending capability
        and returned whichever had the newest created_at with NO requester
        filter -- an operator approving/denying their own session's latest
        request via the documented 'latest' shorthand could silently act on
        a completely different requester's pending capability instead
        (created moments later, whether by a benign concurrent agent or one
        racing to submit right before the operator hits enter)."""
        store = CapabilityStore(tmp_path, now=lambda: 1000.0)
        _make_pending(store, tool="transfer-50", requester="bob-session")
        _make_pending(store, tool="transfer-999999", requester="mallory-session")
        with pytest.raises(CapabilityError, match="multiple requesters"):
            _resolve_capability(store, "latest", now=1000.0)


# ── cmd_executor_approve ─────────────────────────────────────────────────────────

class TestApprove:
    def test_happy_path(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store, tool="stripe-spend", requester="agent1")
        digest = _pending_digest(store, cap_id)
        rc = cmd_executor_approve(Namespace(
            capability_id=cap_id, approved_by="operator",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 0
        assert store.get(cap_id).is_approved

    def test_latest_resolves_and_approves(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store, requester="alice")
        rc = cmd_executor_approve(Namespace(
            capability_id="latest", approved_by="op",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 0
        assert store.get(cap_id).is_approved

    def test_digest_matched(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store, requester="alice")
        digest = _pending_digest(store, cap_id)
        rc = cmd_executor_approve(Namespace(
            capability_id=cap_id, approved_by="operator",
            digest=digest, state_dir=str(tmp_path),
        ))
        assert rc == 0
        assert store.get(cap_id).is_approved

    def test_digest_mismatch_rejected(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store, requester="alice")
        rc = cmd_executor_approve(Namespace(
            capability_id=cap_id, approved_by="operator",
            digest="0" * 64, state_dir=str(tmp_path),
        ))
        assert rc == 1
        assert store.get(cap_id).is_pending  # not consumed

    def test_invalid_capability(self, tmp_path):
        rc = cmd_executor_approve(Namespace(
            capability_id="nope", approved_by="operator",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 1

    def test_expired_capability_rejected(self, tmp_path):
        clock = [1000.0]
        store = CapabilityStore(tmp_path, now=lambda: clock[0])
        cap_id = _make_pending(store, requester="alice")
        clock[0] += 3601
        rc = cmd_executor_approve(Namespace(
            capability_id=cap_id, approved_by="operator",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 1
        assert store.get(cap_id).is_pending

    def test_already_approved_rejected(self, tmp_path):
        cap_id = _make_approved(CapabilityStore(tmp_path))
        rc = cmd_executor_approve(Namespace(
            capability_id=cap_id, approved_by="op",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 1


# ── cmd_executor_deny ────────────────────────────────────────────────────────────

class TestDeny:
    def test_happy_path(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store)
        rc = cmd_executor_deny(Namespace(
            capability_id=cap_id, denied_by="operator",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 0
        assert store.get(cap_id).status == "denied"

    def test_digest_matched(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store)
        digest = _pending_digest(store, cap_id)
        rc = cmd_executor_deny(Namespace(
            capability_id=cap_id, denied_by="op",
            digest=digest, state_dir=str(tmp_path),
        ))
        assert rc == 0
        assert store.get(cap_id).status == "denied"

    def test_digest_mismatch_rejected(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store)
        rc = cmd_executor_deny(Namespace(
            capability_id=cap_id, denied_by="op",
            digest="0" * 64, state_dir=str(tmp_path),
        ))
        assert rc == 1
        assert store.get(cap_id).is_pending  # untouched

    def test_missing_denied_by_no_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("USER", raising=False)
        monkeypatch.delenv("USERNAME", raising=False)
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store)
        rc = cmd_executor_deny(Namespace(
            capability_id=cap_id, denied_by=None,
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 2

    def test_denied_by_fallsback_to_user_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("USER", "authed-op")
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store)
        rc = cmd_executor_deny(Namespace(
            capability_id=cap_id, denied_by=None,
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 0

    def test_invalid_capability(self, tmp_path):
        rc = cmd_executor_deny(Namespace(
            capability_id="nonexistent", denied_by="op",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 1

    def test_already_denied_rejected(self, tmp_path):
        store = CapabilityStore(tmp_path)
        cap_id = _make_pending(store)
        store.deny(cap_id, denied_by="op")
        rc = cmd_executor_deny(Namespace(
            capability_id=cap_id, denied_by="op",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 1

    def test_already_approved_rejected(self, tmp_path):
        cap_id = _make_approved(CapabilityStore(tmp_path))
        rc = cmd_executor_deny(Namespace(
            capability_id=cap_id, denied_by="op",
            digest=None, state_dir=str(tmp_path),
        ))
        assert rc == 1


# ── cmd_executor_start ────────────────────────────────────────────────────────────

class TestStart:
    def test_keyboard_interrupt_returns_zero(self, tmp_path, monkeypatch):
        def _fake_serve(*args, **kwargs):
            raise KeyboardInterrupt()

        monkeypatch.setattr(
            "custodian.executor.service.serve_forever", _fake_serve,
        )
        rc = cmd_executor_start(Namespace(
            skills_root=None, socket=str(tmp_path / "test.sock"),
        ))
        assert rc == 0

    def test_default_socket_path(self):
        path = _default_socket_path()
        assert isinstance(path, Path)
        assert path.name == "executor.sock"
