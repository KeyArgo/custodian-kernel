"""Extended matrix tests for custodian.policy.evaluator.decide."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from custodian.policy.evaluator import decide
from custodian.policy.loader import parse_policy
from custodian.types import AuthorityState, Band, SpendRequest, Verdict


AMOUNTS = [0.01, 0.50, 0.51, 1.00, 2.00, 50.00]
SPENT_CASES = [
    ("fresh", 0.00),
    ("mid", 5.00),
    ("near", 9.75),
    ("at_cap", 10.00),
    ("over_cap", 10.50),
]
BANDS = [Band.L0, Band.L1, Band.L2, Band.L3, Band.L4]
BAND_CAPS = {
    Band.L0: 0.0,
    Band.L1: 0.50,
    Band.L2: 2.00,
    Band.L3: 50.00,
    Band.L4: None,
}


@dataclass(frozen=True)
class DecisionCase:
    case_id: str
    band: Band
    amount: float
    spent: float
    expected_verdict: Verdict
    expects_approval_fragment: bool
    expects_band_cap_fragment: bool
    expects_session_fragment: bool


def make_policy(default_band: Band):
    return parse_policy(
        {
            "version": "1.0",
            "default_band": default_band.value,
            "bands": {
                "L0": {"max_spend": 0.0, "requires_approval": False},
                "L1": {"max_spend": 0.50, "requires_approval": False},
                "L2": {"max_spend": 2.00, "requires_approval": False},
                "L3": {"max_spend": 50.00, "requires_approval": True, "approval_backend": "twilio_verify"},
                "L4": {"max_spend": None, "requires_approval": True, "approval_backend": "twilio_verify"},
            },
            "rules": [],
            "escalation": {"timeout_seconds": 600, "on_timeout": "deny", "retry_count": 0},
        }
    )


def make_state(spent: float) -> AuthorityState:
    return AuthorityState(
        band=Band.L2,
        per_action_cap=2.0,
        session_cap=10.0,
        spent_this_session=spent,
    )


def build_cases() -> list[DecisionCase]:
    cases: list[DecisionCase] = []
    for band in BANDS:
        for amount in AMOUNTS:
            for spent_name, spent in SPENT_CASES:
                cap = BAND_CAPS[band]
                requires_approval = band in {Band.L3, Band.L4}
                over_band_cap = cap is not None and amount > cap
                over_session_cap = amount > make_state(spent).remaining_session_budget()
                expected_verdict = (
                    Verdict.ESCALATION_REQUIRED
                    if requires_approval or over_band_cap or over_session_cap
                    else Verdict.AUTONOMOUS
                )
                cases.append(
                    DecisionCase(
                        case_id=f"{band.value}-{amount:.2f}-{spent_name}",
                        band=band,
                        amount=amount,
                        spent=spent,
                        expected_verdict=expected_verdict,
                        expects_approval_fragment=requires_approval,
                        expects_band_cap_fragment=over_band_cap,
                        expects_session_fragment=over_session_cap,
                    )
                )
    return cases


DECISION_CASES = build_cases()


class TestExtendedDecideMatrix:
    @pytest.mark.parametrize("case", DECISION_CASES, ids=lambda case: case.case_id)
    def test_decide_returns_expected_verdict(self, case: DecisionCase):
        decision = decide(
            SpendRequest(amount=case.amount, description=f"{case.band.value} amount {case.amount:.2f}"),
            make_state(case.spent),
            make_policy(case.band),
        )
        assert decision.verdict == case.expected_verdict

    @pytest.mark.parametrize("case", DECISION_CASES, ids=lambda case: case.case_id)
    def test_decide_returns_the_selected_band(self, case: DecisionCase):
        decision = decide(
            SpendRequest(amount=case.amount, description=f"{case.band.value} amount {case.amount:.2f}"),
            make_state(case.spent),
            make_policy(case.band),
        )
        assert decision.band == case.band

    @pytest.mark.parametrize("case", DECISION_CASES, ids=lambda case: case.case_id)
    def test_reason_includes_approval_fragment_only_when_expected(self, case: DecisionCase):
        decision = decide(
            SpendRequest(amount=case.amount, description=f"{case.band.value} amount {case.amount:.2f}"),
            make_state(case.spent),
            make_policy(case.band),
        )
        assert (f"band {case.band.value} always requires approval" in decision.reason) is case.expects_approval_fragment

    @pytest.mark.parametrize("case", DECISION_CASES, ids=lambda case: case.case_id)
    def test_reason_includes_band_cap_fragment_only_when_expected(self, case: DecisionCase):
        decision = decide(
            SpendRequest(amount=case.amount, description=f"{case.band.value} amount {case.amount:.2f}"),
            make_state(case.spent),
            make_policy(case.band),
        )
        assert ("exceeds band" in decision.reason) is case.expects_band_cap_fragment

    @pytest.mark.parametrize("case", DECISION_CASES, ids=lambda case: case.case_id)
    def test_reason_includes_session_fragment_only_when_expected(self, case: DecisionCase):
        decision = decide(
            SpendRequest(amount=case.amount, description=f"{case.band.value} amount {case.amount:.2f}"),
            make_state(case.spent),
            make_policy(case.band),
        )
        assert ("exceeds remaining session budget" in decision.reason) is case.expects_session_fragment


class TestSpecificBandExpectations:
    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_l3_always_requires_approval(self, amount: float):
        decision = decide(
            SpendRequest(amount=amount, description=f"L3 amount {amount:.2f}"),
            make_state(0.0),
            make_policy(Band.L3),
        )
        assert decision.verdict == Verdict.ESCALATION_REQUIRED

    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_l4_always_requires_approval(self, amount: float):
        decision = decide(
            SpendRequest(amount=amount, description=f"L4 amount {amount:.2f}"),
            make_state(0.0),
            make_policy(Band.L4),
        )
        assert decision.verdict == Verdict.ESCALATION_REQUIRED

    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_l0_rejects_positive_amounts_into_escalation(self, amount: float):
        decision = decide(
            SpendRequest(amount=amount, description=f"L0 amount {amount:.2f}"),
            make_state(0.0),
            make_policy(Band.L0),
        )
        assert decision.verdict == Verdict.ESCALATION_REQUIRED

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            (0.01, Verdict.AUTONOMOUS),
            (0.50, Verdict.AUTONOMOUS),
            (0.51, Verdict.ESCALATION_REQUIRED),
            (1.00, Verdict.ESCALATION_REQUIRED),
            (2.00, Verdict.ESCALATION_REQUIRED),
            (50.00, Verdict.ESCALATION_REQUIRED),
        ],
    )
    def test_l1_exact_demo_amounts(self, amount: float, expected: Verdict):
        decision = decide(
            SpendRequest(amount=amount, description=f"L1 amount {amount:.2f}"),
            make_state(0.0),
            make_policy(Band.L1),
        )
        assert decision.verdict == expected

    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            (0.01, Verdict.AUTONOMOUS),
            (0.50, Verdict.AUTONOMOUS),
            (0.51, Verdict.AUTONOMOUS),
            (1.00, Verdict.AUTONOMOUS),
            (2.00, Verdict.AUTONOMOUS),
            (50.00, Verdict.ESCALATION_REQUIRED),
        ],
    )
    def test_l2_exact_demo_amounts(self, amount: float, expected: Verdict):
        decision = decide(
            SpendRequest(amount=amount, description=f"L2 amount {amount:.2f}"),
            make_state(0.0),
            make_policy(Band.L2),
        )
        assert decision.verdict == expected

    @pytest.mark.parametrize("amount", AMOUNTS)
    def test_session_near_cap_triggers_escalation_when_amount_exceeds_remaining(self, amount: float):
        decision = decide(
            SpendRequest(amount=amount, description=f"near-cap amount {amount:.2f}"),
            make_state(9.75),
            make_policy(Band.L2),
        )
        assert decision.verdict == (
            Verdict.ESCALATION_REQUIRED if amount > 0.25 else Verdict.AUTONOMOUS
        )

