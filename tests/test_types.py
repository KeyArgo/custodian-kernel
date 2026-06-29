"""Tests for custodian.types."""
from __future__ import annotations

import time

from custodian.types import AuditEntry, AuthorityState, Band, Decision, PendingApproval, SpendRequest, Verdict


class TestAuthorityState:
    def test_remaining_session_budget_full(self):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=0.0)
        assert state.remaining_session_budget() == 10.0

    def test_remaining_session_budget_partial(self):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=4.50)
        assert state.remaining_session_budget() == 5.50

    def test_remaining_session_budget_exhausted(self):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=10.0)
        assert state.remaining_session_budget() == 0.0

    def test_remaining_session_budget_over(self):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=12.0)
        assert state.remaining_session_budget() == -2.0

    def test_to_dict_roundtrip(self):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=3.0)
        d = state.to_dict()
        restored = AuthorityState.from_dict(d)
        assert restored == state

    def test_to_dict_roundtrip_zero_spent(self):
        state = AuthorityState(band=Band.L0, per_action_cap=0.0, session_cap=0.0, spent_this_session=0.0)
        d = state.to_dict()
        restored = AuthorityState.from_dict(d)
        assert restored == state

    def test_from_dict_default_spent(self):
        d = {"band": "L2", "per_action_cap": 2.0, "session_cap": 10.0}
        state = AuthorityState.from_dict(d)
        assert state.spent_this_session == 0.0


class TestAuditEntry:
    def test_to_dict_includes_all_fields(self):
        entry = AuditEntry(
            event="executed",
            amount=45.0,
            description="Backup automation license renewal for NAS systems",
            band=Band.L2,
            ts=1741234567.0,
            approved_by="Operator",
            payment_intent_id="pi_3TkZWEPfSF4TGXT90AWlrnle",
        )
        d = entry.to_dict()
        assert d["event"] == "executed"
        assert d["amount"] == 45.0
        assert d["approved_by"] == "Operator"
        assert d["payment_intent_id"] == "pi_3TkZWEPfSF4TGXT90AWlrnle"
        assert d["band"] == "L2"

    def test_to_dict_excludes_null_fields(self):
        entry = AuditEntry(event="executed", amount=1.50, description="test", band=Band.L1)
        d = entry.to_dict()
        assert "approved_by" not in d
        assert "denied_by" not in d

    def test_to_dict_from_dict_roundtrip(self):
        entry = AuditEntry(
            event="executed",
            amount=45.0,
            description="Backup automation license renewal for NAS systems",
            band=Band.L2,
            ts=1741234567.0,
            approved_by="Operator",
            payment_intent_id="pi_3TkZWEPfSF4TGXT90AWlrnle",
        )
        d = entry.to_dict()
        restored = AuditEntry.from_dict(d)
        assert restored.event == entry.event
        assert restored.amount == entry.amount
        assert restored.description == entry.description
        assert restored.band == entry.band
        assert restored.ts == entry.ts
        assert restored.approved_by == entry.approved_by
        assert restored.payment_intent_id == entry.payment_intent_id

    def test_from_dict_defaults(self):
        d = {"event": "executed", "amount": 10.0, "description": "test"}
        entry = AuditEntry.from_dict(d)
        assert entry.band == "L2"
        assert entry.approved_by is None

    def test_from_dict_with_band_string(self):
        d = {"event": "denied", "amount": 0.0, "description": "denied", "band": "L3"}
        entry = AuditEntry.from_dict(d)
        assert entry.band == "L3"


class TestPendingApproval:
    def test_to_dict_from_dict_roundtrip(self):
        pa = PendingApproval(
            amount=45.0,
            description="Backup automation license renewal for NAS systems",
            reason="exceeds L2 cap",
            created_at=1741234567.0,
        )
        d = pa.to_dict()
        restored = PendingApproval.from_dict(d)
        assert restored.amount == pa.amount
        assert restored.description == pa.description
        assert restored.reason == pa.reason
        assert restored.created_at == pa.created_at

    def test_from_dict_default_created_at(self):
        before = time.time()
        d = {"amount": 10.0, "description": "test", "reason": "testing"}
        pa = PendingApproval.from_dict(d)
        after = time.time()
        assert before <= pa.created_at <= after

    def test_from_dict_default_reason(self):
        d = {"amount": 10.0, "description": "test"}
        pa = PendingApproval.from_dict(d)
        assert pa.reason == ""

    def test_is_expired_fresh(self):
        pa = PendingApproval(amount=10.0, description="test", reason="test", created_at=time.time())
        assert not pa.is_expired(ttl_seconds=600)

    def test_is_expired_old(self):
        pa = PendingApproval(
            amount=10.0, description="test", reason="test", created_at=time.time() - 601
        )
        assert pa.is_expired(ttl_seconds=600)


class TestDecision:
    def test_autonomous_decision(self):
        request = SpendRequest(amount=1.50, description="small purchase")
        decision = Decision(
            verdict=Verdict.AUTONOMOUS,
            request=request,
            reason="$1.50 within band L2",
            band=Band.L2,
        )
        assert decision.verdict == Verdict.AUTONOMOUS
        assert decision.request.amount == 1.50
        assert decision.band == Band.L2

    def test_escalation_decision(self):
        request = SpendRequest(amount=45.0, description="Backup automation license renewal for NAS systems")
        decision = Decision(
            verdict=Verdict.ESCALATION_REQUIRED,
            request=request,
            reason="$45.00 exceeds L2 cap",
            band=Band.L2,
        )
        assert decision.verdict == Verdict.ESCALATION_REQUIRED
        assert decision.reason == "$45.00 exceeds L2 cap"

    def test_denied_decision(self):
        request = SpendRequest(amount=100.0, description="large purchase")
        decision = Decision(
            verdict=Verdict.DENIED,
            request=request,
            reason="explicitly denied by operator",
            band=Band.L2,
        )
        assert decision.verdict == Verdict.DENIED


class TestSpendRequest:
    def test_default_requested_at(self):
        before = time.time()
        r = SpendRequest(amount=10.0, description="test")
        after = time.time()
        assert before <= r.requested_at <= after

    def test_optional_fields_default_to_none(self):
        r = SpendRequest(amount=10.0, description="test")
        assert r.recipe is None
        assert r.to is None
        assert r.message is None
