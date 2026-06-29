"""Tests for custodian.packs.base."""
from __future__ import annotations

from dataclasses import asdict

import pytest

from custodian.packs.base import (
    Claim,
    ClaimStatus,
    Envelope,
    EvidenceSpan,
    PolicyPack,
    TriageResult,
    _compare,
    _resolve,
    verify_claims,
)


def make_claim(**overrides) -> Claim:
    data = {
        "id": "claim-1",
        "statement": "package was not delivered",
        "customer_quote": "it never showed up",
        "ledger_path": "order.delivered",
        "relation": "eq",
        "asserted": False,
    }
    data.update(overrides)
    return Claim(**data)


def make_envelope(**overrides) -> Envelope:
    data = {
        "case_id": "case-1",
        "customer_id": "cust-1",
        "order_id": "order-1",
        "amount": 39.0,
        "requested_action": "refund.create",
        "claims": [make_claim()],
        "policy_clauses_cited": [EvidenceSpan(source="policy", quote="Refunds allowed for defects.")],
        "recommended_disposition": "approve_recommended",
        "confidence": 0.82,
        "agent_summary": "Customer says the package never arrived.",
    }
    data.update(overrides)
    return Envelope(**data)


class DemoPack(PolicyPack):
    def __init__(self, scope: dict | None = None):
        self.scope = scope or {"order": {"delivered": True}}

    def ledger_scope(self, envelope: Envelope) -> dict:
        return self.scope

    def adapter(self, envelope: Envelope) -> tuple[str, list[str], str]:
        return "demo_disposition", ["demo reason"], "demo explanation"


class TestClaimStatus:
    def test_verified_value_is_stable(self):
        assert ClaimStatus.VERIFIED.value == "verified"

    def test_contradicted_value_is_stable(self):
        assert ClaimStatus.CONTRADICTED.value == "contradicted"

    def test_unverifiable_value_is_stable(self):
        assert ClaimStatus.UNVERIFIABLE.value == "unverifiable"

    def test_pending_value_is_stable(self):
        assert ClaimStatus.PENDING.value == "pending"


class TestClaim:
    def test_from_dict_builds_claim(self):
        claim = Claim.from_dict(
            {
                "id": "c1",
                "statement": "status is delivered",
                "customer_quote": "tracking says delivered",
                "ledger_path": "delivery.status",
                "relation": "eq",
                "asserted": "delivered",
            }
        )
        assert claim == Claim(
            id="c1",
            statement="status is delivered",
            customer_quote="tracking says delivered",
            ledger_path="delivery.status",
            relation="eq",
            asserted="delivered",
        )

    def test_from_dict_defaults_customer_quote_to_empty_string(self):
        claim = Claim.from_dict(
            {
                "id": "c1",
                "statement": "status is delivered",
                "ledger_path": "delivery.status",
                "relation": "eq",
            }
        )
        assert claim.customer_quote == ""


class TestEnvelope:
    def test_from_dict_builds_nested_claims_and_evidence(self):
        envelope = Envelope.from_dict(
            {
                "case_id": "case-1",
                "customer_id": "cust-1",
                "order_id": "order-1",
                "amount": "39.00",
                "requested_action": "refund.create",
                "claims": [
                    {
                        "id": "c1",
                        "statement": "package was delivered",
                        "ledger_path": "order.delivered",
                        "relation": "eq",
                        "asserted": True,
                    }
                ],
                "policy_clauses_cited": [
                    {"source": "policy", "quote": "Delivered orders are not refundable.", "locator": "refunds.md:10"}
                ],
                "recommended_disposition": "deny_recommended",
                "confidence": "0.4",
                "agent_summary": "The order shows as delivered.",
            }
        )
        assert envelope == Envelope(
            case_id="case-1",
            customer_id="cust-1",
            order_id="order-1",
            amount=39.0,
            requested_action="refund.create",
            claims=[
                Claim(
                    id="c1",
                    statement="package was delivered",
                    customer_quote="",
                    ledger_path="order.delivered",
                    relation="eq",
                    asserted=True,
                )
            ],
            policy_clauses_cited=[
                EvidenceSpan(
                    source="policy",
                    quote="Delivered orders are not refundable.",
                    locator="refunds.md:10",
                )
            ],
            recommended_disposition="deny_recommended",
            confidence=0.4,
            agent_summary="The order shows as delivered.",
        )

    def test_from_dict_defaults_requested_action(self):
        envelope = Envelope.from_dict(
            {
                "case_id": "case-1",
                "customer_id": "cust-1",
                "order_id": "order-1",
                "amount": 12.0,
            }
        )
        assert envelope.requested_action == "refund.create"

    def test_from_dict_defaults_optional_fields(self):
        envelope = Envelope.from_dict(
            {
                "case_id": "case-1",
                "customer_id": "cust-1",
                "order_id": "order-1",
                "amount": 12.0,
            }
        )
        assert envelope == Envelope(
            case_id="case-1",
            customer_id="cust-1",
            order_id="order-1",
            amount=12.0,
            requested_action="refund.create",
            claims=[],
            policy_clauses_cited=[],
            recommended_disposition="escalate_ambiguous",
            confidence=0.0,
            agent_summary="",
        )


class TestResolve:
    @pytest.mark.parametrize(
        ("obj", "dotted", "expected"),
        [
            ({"delivery": {"status": "delivered"}}, "delivery.status", ("delivered", True)),
            ({"delivery": {"status": {"code": "ok"}}}, "delivery.status.code", ("ok", True)),
            ({"order": {"items": {"0": {"price": 19.99}}}}, "order.items.0.price", (19.99, True)),
            ({"customer": {"profile": {"name": "Ada"}}}, "customer.profile.name", ("Ada", True)),
            ({"customer": {"profile": {"name": None}}}, "customer.profile.name", (None, True)),
            ({"order": {"totals": {"refund": 0}}}, "order.totals.refund", (0, True)),
            ({"order": {"totals": {"refund": False}}}, "order.totals.refund", (False, True)),
            ({"order": {"id": "o-1"}}, "order.id", ("o-1", True)),
            ({"order": {"id": "o-1"}}, "order.missing", (None, False)),
            ({"order": {"items": {}}}, "order.items.0.price", (None, False)),
            ({"order": {"items": {"0": {}}}}, "order.items.0.price", (None, False)),
            ({"order": "not-a-dict"}, "order.id", (None, False)),
        ],
    )
    def test_resolve_returns_expected_tuple(self, obj: dict, dotted: str, expected: tuple[object, bool]):
        assert _resolve(obj, dotted) == expected


class TestCompare:
    @pytest.mark.parametrize(
        ("actual", "relation", "asserted"),
        [
            ("delivered", "eq", "delivered"),
            ("delivered", "neq", "cancelled"),
            (5, "gt", 4),
            (4, "lt", 5),
            (5, "gte", 5),
            (4, "lte", 4),
            ("present", "exists", None),
            (None, "absent", None),
        ],
    )
    def test_compare_true_cases(self, actual: object, relation: str, asserted: object):
        assert _compare(actual, relation, asserted) is True

    @pytest.mark.parametrize(
        ("actual", "relation", "asserted"),
        [
            ("delivered", "eq", "cancelled"),
            ("delivered", "neq", "delivered"),
            (4, "gt", 5),
            (5, "lt", 4),
            (4, "gte", 5),
            (5, "lte", 4),
            (None, "exists", None),
            ("present", "absent", None),
        ],
    )
    def test_compare_false_cases(self, actual: object, relation: str, asserted: object):
        assert _compare(actual, relation, asserted) is False

    @pytest.mark.parametrize(
        ("actual", "relation", "asserted"),
        [
            ("5", "gt", 4),
            ("5", "lt", 4),
            ("5", "gte", 4),
            ("5", "lte", 4),
            (4, "gt", "3"),
            (4, "lt", "3"),
            (4, "gte", "3"),
            (4, "lte", "3"),
        ],
    )
    def test_compare_type_mismatch_returns_false(self, actual: object, relation: str, asserted: object):
        assert _compare(actual, relation, asserted) is False

    def test_compare_unknown_relation_raises(self):
        with pytest.raises(ValueError, match="unknown relation"):
            _compare(1, "wat", 1)


class TestVerifyClaims:
    @pytest.mark.parametrize(
        ("claim", "scope", "expected_status", "expected_actual"),
        [
            (make_claim(relation="eq", asserted="delivered", ledger_path="delivery.status"), {"delivery": {"status": "delivered"}}, ClaimStatus.VERIFIED, "delivered"),
            (make_claim(relation="eq", asserted="lost", ledger_path="delivery.status"), {"delivery": {"status": "delivered"}}, ClaimStatus.CONTRADICTED, "delivered"),
            (make_claim(relation="neq", asserted="cancelled", ledger_path="delivery.status"), {"delivery": {"status": "delivered"}}, ClaimStatus.VERIFIED, "delivered"),
            (make_claim(relation="neq", asserted="delivered", ledger_path="delivery.status"), {"delivery": {"status": "delivered"}}, ClaimStatus.CONTRADICTED, "delivered"),
            (make_claim(relation="gt", asserted=10, ledger_path="order.total"), {"order": {"total": 20}}, ClaimStatus.VERIFIED, 20),
            (make_claim(relation="gt", asserted=20, ledger_path="order.total"), {"order": {"total": 10}}, ClaimStatus.CONTRADICTED, 10),
            (make_claim(relation="lt", asserted=20, ledger_path="order.total"), {"order": {"total": 10}}, ClaimStatus.VERIFIED, 10),
            (make_claim(relation="lt", asserted=5, ledger_path="order.total"), {"order": {"total": 10}}, ClaimStatus.CONTRADICTED, 10),
            (make_claim(relation="gte", asserted=10, ledger_path="order.total"), {"order": {"total": 10}}, ClaimStatus.VERIFIED, 10),
            (make_claim(relation="gte", asserted=11, ledger_path="order.total"), {"order": {"total": 10}}, ClaimStatus.CONTRADICTED, 10),
            (make_claim(relation="lte", asserted=10, ledger_path="order.total"), {"order": {"total": 10}}, ClaimStatus.VERIFIED, 10),
            (make_claim(relation="lte", asserted=9, ledger_path="order.total"), {"order": {"total": 10}}, ClaimStatus.CONTRADICTED, 10),
            (make_claim(relation="exists", asserted=None, ledger_path="order.delivered"), {"order": {"delivered": False}}, ClaimStatus.VERIFIED, False),
            (make_claim(relation="exists", asserted=None, ledger_path="order.delivered"), {"order": {"delivered": None}}, ClaimStatus.CONTRADICTED, None),
            (make_claim(relation="absent", asserted=None, ledger_path="order.missing"), {"order": {}}, ClaimStatus.VERIFIED, None),
            (make_claim(relation="absent", asserted=None, ledger_path="order.note"), {"order": {"note": None}}, ClaimStatus.VERIFIED, None),
            (make_claim(relation="absent", asserted=None, ledger_path="order.note"), {"order": {"note": "present"}}, ClaimStatus.CONTRADICTED, "present"),
            (make_claim(relation="eq", asserted=True, ledger_path="order.missing"), {"order": {}}, ClaimStatus.UNVERIFIABLE, None),
            (make_claim(relation="gt", asserted=5, ledger_path="order.total"), {"order": {"total": "9"}}, ClaimStatus.CONTRADICTED, "9"),
        ],
    )
    def test_verify_claims_assigns_expected_status(
        self,
        claim: Claim,
        scope: dict,
        expected_status: ClaimStatus,
        expected_actual: object,
    ):
        result = verify_claims([claim], scope)
        assert (result[0].status, result[0].actual) == (expected_status, expected_actual)

    def test_verify_claims_handles_multiple_mixed_statuses(self):
        claims = [
            make_claim(id="verified", relation="eq", asserted=True, ledger_path="order.delivered"),
            make_claim(id="contradicted", relation="eq", asserted=False, ledger_path="order.delivered"),
            make_claim(id="missing", relation="eq", asserted=True, ledger_path="order.unknown"),
        ]
        verified = verify_claims(claims, {"order": {"delivered": True}})
        assert [claim.status for claim in verified] == [
            ClaimStatus.VERIFIED,
            ClaimStatus.CONTRADICTED,
            ClaimStatus.UNVERIFIABLE,
        ]

    def test_verify_claims_resolves_nested_dotted_path(self):
        claim = make_claim(
            ledger_path="order.items.0.price",
            relation="eq",
            asserted=19.99,
        )
        verified = verify_claims([claim], {"order": {"items": {"0": {"price": 19.99}}}})
        assert verified[0].status == ClaimStatus.VERIFIED

    def test_verify_claims_type_mismatch_does_not_raise(self):
        claim = make_claim(ledger_path="order.total", relation="gt", asserted=5)
        verified = verify_claims([claim], {"order": {"total": "9"}})
        assert verified[0].status == ClaimStatus.CONTRADICTED


class TestTriageResult:
    def test_to_panel_includes_final_action(self):
        result = TriageResult(
            envelope=make_envelope(),
            contradictions=[],
            adapter_disposition="approve_recommended",
            adapter_reasons=["within policy"],
            why_not_a_script="Because text matters.",
            kernel_verdict="escalation_required",
            kernel_reason="band L3 always requires approval",
            final_action="needs_human_review",
            ledger_scope={"order": {"delivered": False}},
        )
        assert result.to_panel()["final_action"] == "needs_human_review"

    def test_to_panel_serializes_claim_status_values(self):
        result = TriageResult(
            envelope=make_envelope(claims=[make_claim(status=ClaimStatus.CONTRADICTED, actual=True)]),
            contradictions=[],
            adapter_disposition="flag_abuse",
            adapter_reasons=["claim refuted"],
            why_not_a_script="Ground truth contradicted the story.",
            kernel_verdict="escalation_required",
            kernel_reason="band L3 always requires approval",
        )
        assert result.to_panel()["claims"][0]["status"] == "contradicted"

    def test_to_panel_reports_contradiction_count(self):
        contradicted = make_claim(id="c2", status=ClaimStatus.CONTRADICTED, actual=True)
        result = TriageResult(
            envelope=make_envelope(claims=[contradicted]),
            contradictions=[contradicted],
            adapter_disposition="flag_abuse",
            adapter_reasons=["claim refuted"],
            why_not_a_script="Ground truth contradicted the story.",
            kernel_verdict="escalation_required",
            kernel_reason="band L3 always requires approval",
        )
        assert result.to_panel()["contradiction_count"] == 1

    def test_to_panel_serializes_policy_clauses(self):
        result = TriageResult(
            envelope=make_envelope(
                policy_clauses_cited=[EvidenceSpan(source="policy", quote="quoted", locator="a.md:1")]
            ),
            contradictions=[],
            adapter_disposition="approve_recommended",
            adapter_reasons=["within policy"],
            why_not_a_script="Because text matters.",
            kernel_verdict="escalation_required",
            kernel_reason="band L3 always requires approval",
        )
        assert result.to_panel()["policy_clauses_cited"][0] == {"quote": "quoted", "locator": "a.md:1"}

    def test_to_panel_includes_agent_recommendation(self):
        result = TriageResult(
            envelope=make_envelope(recommended_disposition="deny_recommended"),
            contradictions=[],
            adapter_disposition="deny_recommended",
            adapter_reasons=["out of window"],
            why_not_a_script="No special handling needed.",
            kernel_verdict="escalation_required",
            kernel_reason="band L3 always requires approval",
        )
        assert result.to_panel()["agent_recommended"] == "deny_recommended"


class TestPolicyPack:
    def test_default_name_is_base(self):
        assert PolicyPack.name == "base"

    def test_default_requested_action_is_noop(self):
        assert PolicyPack.requested_action == "noop"

    def test_default_autonomous_dispositions_is_empty(self):
        assert PolicyPack.autonomous_dispositions == frozenset()

    def test_subclass_can_return_scope(self):
        pack = DemoPack(scope={"order": {"delivered": False}})
        assert pack.ledger_scope(make_envelope()) == {"order": {"delivered": False}}

    def test_evidence_span_round_trips_via_asdict(self):
        span = EvidenceSpan(source="policy", quote="quoted", locator="policy.md:10")
        assert asdict(span) == {"source": "policy", "quote": "quoted", "locator": "policy.md:10"}
