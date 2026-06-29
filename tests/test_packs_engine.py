"""Tests for custodian.packs.engine."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from custodian.packs.base import Claim, ClaimStatus, Envelope, EvidenceSpan, PolicyPack
from custodian.packs.engine import _final_action, triage
from custodian.policy.loader import parse_policy
from custodian.types import AuthorityState, Band


def make_policy(default_band: str = "L2"):
    return parse_policy(
        {
            "version": "1.0",
            "default_band": default_band,
            "bands": {
                "L0": {"max_spend": 0.0, "requires_approval": False},
                "L1": {"max_spend": 0.50, "requires_approval": False},
                "L2": {"max_spend": 2.0, "requires_approval": False},
                "L3": {"max_spend": 50.0, "requires_approval": True, "approval_backend": "twilio_verify"},
                "L4": {"max_spend": None, "requires_approval": True, "approval_backend": "twilio_verify"},
            },
            "rules": [],
            "escalation": {"timeout_seconds": 600, "on_timeout": "deny", "retry_count": 0},
        }
    )


def make_envelope(amount: float = 1.0, claims: list[Claim] | None = None) -> Envelope:
    return Envelope(
        case_id="case-1",
        customer_id="cust-1",
        order_id="order-1",
        amount=amount,
        requested_action="invoice.pay",
        claims=claims or [],
        policy_clauses_cited=[EvidenceSpan(source="policy", quote="A clause")],
        recommended_disposition="auto_pay",
        confidence=0.9,
        agent_summary="Agent summary",
    )


class DummyPack(PolicyPack):
    name = "dummy"
    requested_action = "invoice.pay"

    def __init__(
        self,
        *,
        scope: dict | None = None,
        disposition: str = "auto_pay",
        reasons: list[str] | None = None,
        why: str = "because",
        autonomous_dispositions: frozenset[str] = frozenset({"auto_pay"}),
    ):
        self._scope = scope or {}
        self._disposition = disposition
        self._reasons = reasons or ["clean"]
        self._why = why
        self.autonomous_dispositions = autonomous_dispositions

    def ledger_scope(self, envelope: Envelope) -> dict:
        return self._scope

    def adapter(self, envelope: Envelope) -> tuple[str, list[str], str]:
        return self._disposition, self._reasons, self._why


class TestFinalAction:
    @pytest.mark.parametrize(
        ("disposition", "kernel_verdict", "autonomous_dispositions", "expected"),
        [
            ("auto_pay", "autonomous", frozenset({"auto_pay"}), "executed_autonomously"),
            ("auto_pay", "escalation_required", frozenset({"auto_pay"}), "pending_human_approval"),
            ("auto_pay", "denied", frozenset({"auto_pay"}), "blocked_kill_switch"),
            ("manual_review", "autonomous", frozenset({"auto_pay"}), "needs_human_review"),
            ("manual_review", "escalation_required", frozenset({"auto_pay"}), "needs_human_review"),
            ("manual_review", "denied", frozenset({"auto_pay"}), "blocked_kill_switch"),
        ],
    )
    def test_final_action_resolves_expected_outcome(
        self,
        disposition: str,
        kernel_verdict: str,
        autonomous_dispositions: frozenset[str],
        expected: str,
    ):
        assert _final_action(disposition, kernel_verdict, autonomous_dispositions) == expected


class TestTriage:
    def test_clean_envelope_passes_adapter_disposition_through(self):
        pack = DummyPack(disposition="auto_pay", reasons=["all clear"])
        result = triage(pack, make_envelope(amount=1.0), make_policy("L2"), AuthorityState(Band.L2, 2.0, 10.0))
        assert result.adapter_disposition == "auto_pay"

    def test_contradicted_claim_populates_contradictions(self):
        claim = Claim(
            id="c1",
            statement="invoice matches PO",
            customer_quote="$40.00",
            ledger_path="po.amount",
            relation="eq",
            asserted=40.0,
        )
        pack = DummyPack(scope={"po": {"amount": 45.0}}, disposition="flag_hold")
        result = triage(pack, make_envelope(amount=1.0, claims=[claim]), make_policy("L2"), AuthorityState(Band.L2, 2.0, 10.0))
        assert result.contradictions[0].status == ClaimStatus.CONTRADICTED

    def test_killed_request_returns_denied_verdict(self):
        pack = DummyPack(disposition="auto_pay")
        result = triage(
            pack,
            make_envelope(amount=1.0),
            make_policy("L2"),
            AuthorityState(Band.L2, 2.0, 10.0),
            killed=True,
        )
        assert result.kernel_verdict == "denied"

    def test_killed_request_sets_blocked_kill_switch_action(self):
        pack = DummyPack(disposition="auto_pay")
        result = triage(
            pack,
            make_envelope(amount=1.0),
            make_policy("L2"),
            AuthorityState(Band.L2, 2.0, 10.0),
            killed=True,
        )
        assert result.final_action == "blocked_kill_switch"

    def test_autonomous_disposition_and_kernel_autonomous_executes(self):
        pack = DummyPack(disposition="auto_pay", autonomous_dispositions=frozenset({"auto_pay"}))
        result = triage(pack, make_envelope(amount=1.0), make_policy("L2"), AuthorityState(Band.L2, 2.0, 10.0))
        assert result.final_action == "executed_autonomously"

    def test_autonomous_disposition_and_kernel_escalation_does_not_auto_execute(self):
        pack = DummyPack(disposition="auto_pay", autonomous_dispositions=frozenset({"auto_pay"}))
        result = triage(pack, make_envelope(amount=1.0), make_policy("L3"), AuthorityState(Band.L2, 2.0, 10.0))
        assert result.final_action == "pending_human_approval"

    def test_non_autonomous_disposition_and_kernel_autonomous_still_needs_human_review(self):
        pack = DummyPack(disposition="manual_review", autonomous_dispositions=frozenset({"auto_pay"}))
        result = triage(pack, make_envelope(amount=1.0), make_policy("L2"), AuthorityState(Band.L2, 2.0, 10.0))
        assert result.final_action == "needs_human_review"

    def test_amount_over_band_cap_escalates(self):
        pack = DummyPack(disposition="auto_pay")
        result = triage(pack, make_envelope(amount=2.01), make_policy("L2"), AuthorityState(Band.L2, 2.0, 10.0))
        assert result.kernel_verdict == "escalation_required"

    def test_session_budget_exceeded_escalates(self):
        pack = DummyPack(disposition="auto_pay")
        state = AuthorityState(Band.L2, 2.0, 10.0, spent_this_session=9.5)
        result = triage(pack, make_envelope(amount=1.0), make_policy("L2"), state)
        assert result.kernel_verdict == "escalation_required"

    def test_result_exposes_ledger_scope(self):
        pack = DummyPack(scope={"order": {"delivered": True}})
        result = triage(pack, make_envelope(amount=1.0), make_policy("L2"), AuthorityState(Band.L2, 2.0, 10.0))
        assert result.ledger_scope == {"order": {"delivered": True}}

