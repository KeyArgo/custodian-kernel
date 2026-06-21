"""Tests for custodian.policy: schema, loader, evaluator."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from custodian.exceptions import PolicyNotFoundError, PolicyValidationError
from custodian.policy.evaluator import decide
from custodian.policy.loader import load_policy, parse_policy
from custodian.policy.schema import (
    BandConfig,
    EscalationConfig,
    MatchCondition,
    Policy,
    Rule,
)
from custodian.types import Band, SpendRequest, Verdict


def make_policy_dict(
    version: str = "1.0",
    default_band: str = "L2",
    bands: dict | None = None,
    rules: list | None = None,
    escalation: dict | None = None,
) -> dict:
    return {
        "version": version,
        "default_band": default_band,
        "bands": bands or {
            "L2": {"max_spend": 2.0, "requires_approval": False},
        },
        "rules": rules or [],
        "escalation": escalation or {"timeout_seconds": 600, "on_timeout": "deny", "retry_count": 0},
    }


class TestValidPolicy:
    def test_valid_policy_loads(self, tmp_policy_file: Path):
        policy = load_policy(tmp_policy_file)
        assert policy.version == "1.0"
        assert policy.default_band == Band.L2
        assert Band.L2 in policy.bands
        assert policy.bands[Band.L2].max_spend == 2.0

    def test_valid_policy_has_escalation_defaults(self, tmp_policy_file: Path):
        policy = load_policy(tmp_policy_file)
        assert policy.escalation.timeout_seconds == 600
        assert policy.escalation.on_timeout == "deny"
        assert policy.escalation.retry_count == 0

    def test_policy_not_found_error(self):
        with pytest.raises(PolicyNotFoundError, match="no policy file found"):
            load_policy(Path("/nonexistent/policy.yaml"))


class TestInvalidPolicy:
    def _assert_validation_error(self, raw: dict, msg_substring: str):
        with pytest.raises(PolicyValidationError, match=msg_substring):
            parse_policy(raw)

    def test_missing_version(self):
        raw = make_policy_dict()
        raw.pop("version")
        self._assert_validation_error(raw, "missing required field 'version'")

    def test_missing_bands(self):
        raw = make_policy_dict()
        raw.pop("bands")
        self._assert_validation_error(raw, "missing required field 'bands'")

    def test_undefined_default_band(self):
        raw = make_policy_dict(default_band="L99")
        self._assert_validation_error(raw, "unknown default_band 'L99'")

    def test_requires_approval_without_backend(self):
        raw = make_policy_dict(bands={
            "L2": {"max_spend": 2.0, "requires_approval": True},
        })
        self._assert_validation_error(raw, "requires_approval=true but no approval_backend")

    def test_unknown_approval_backend(self):
        raw = make_policy_dict(bands={
            "L2": {"max_spend": 2.0, "requires_approval": True, "approval_backend": "nonexistent"},
        })
        self._assert_validation_error(raw, "unknown approval_backend 'nonexistent'")

    def test_rule_assigns_undefined_band(self):
        raw = make_policy_dict(rules=[
            {"match": {"skill": "test"}, "assign_band": "L99"},
        ])
        self._assert_validation_error(raw, "unknown assign_band 'L99'")

    def test_negative_max_spend(self):
        raw = make_policy_dict(bands={
            "L2": {"max_spend": -1.0, "requires_approval": False},
        })
        self._assert_validation_error(raw, "max_spend must be >= 0")

    def test_non_positive_escalation_timeout(self):
        raw = make_policy_dict(escalation={"timeout_seconds": 0, "on_timeout": "deny", "retry_count": 0})
        self._assert_validation_error(raw, "timeout_seconds must be positive")

    def test_invalid_on_timeout(self):
        raw = make_policy_dict(escalation={"timeout_seconds": 600, "on_timeout": "banana", "retry_count": 0})
        self._assert_validation_error(raw, "on_timeout must be 'deny' or 'retry'")

    def test_negative_retry_count(self):
        raw = make_policy_dict(escalation={"timeout_seconds": 600, "on_timeout": "deny", "retry_count": -1})
        self._assert_validation_error(raw, "retry_count must be >= 0")


class TestDecide:
    def test_in_band_amount_autonomous(self, loaded_policy, default_authority):
        request = SpendRequest(amount=1.50, description="Small autonomous spend")
        result = decide(request, default_authority, loaded_policy)
        assert result.verdict == Verdict.AUTONOMOUS

    def test_amount_exceeding_band_cap_escalates(self, loaded_policy, default_authority):
        request = SpendRequest(
            amount=45.0,
            description="Backup automation license renewal for NAS systems",
        )
        result = decide(request, default_authority, loaded_policy)
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_large_amount_escalates(self, loaded_policy, default_authority):
        request = SpendRequest(
            amount=100.0,
            description="Purchase NVMe SSD for Unraid cache pool to prevent outage",
        )
        result = decide(request, default_authority, loaded_policy)
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_exceeds_session_budget_escalates(self, loaded_policy, partial_authority):
        request = SpendRequest(amount=6.00, description="Over remaining session budget")
        result = decide(request, partial_authority, loaded_policy)
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_requires_approval_band_always_escalates(self, loaded_policy, default_authority):
        request = SpendRequest(amount=1.00, description="Small but L3 band requires approval")
        policy = loaded_policy
        policy.bands[Band.L2].requires_approval = True
        result = decide(request, default_authority, policy)
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_rule_matching_by_skill_name(self, default_authority):
        raw = make_policy_dict(
            bands={
                "L1": {"max_spend": 0.50, "requires_approval": False},
                "L2": {"max_spend": 2.0, "requires_approval": False},
            },
            rules=[
                {"match": {"skill": "low-cost-tool"}, "assign_band": "L1"},
            ],
        )
        policy = parse_policy(raw)
        request = SpendRequest(amount=1.00, description="routed by skill")
        result = decide(request, default_authority, policy, skill="low-cost-tool")
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_rule_matching_by_context_flag(self, default_authority):
        raw = make_policy_dict(
            rules=[
                {"match": {"skill": "provision-server"}, "assign_band": "L5"},
            ],
        )
        with pytest.raises(PolicyValidationError, match="unknown assign_band 'L5'"):
            parse_policy(raw)

    def test_rule_context_flag_matches(self, default_authority):
        raw = make_policy_dict(
            bands={
                "L0": {"max_spend": 0, "requires_approval": False},
                "L2": {"max_spend": 2.0, "requires_approval": False},
                "L4": {"max_spend": None, "requires_approval": True, "approval_backend": "twilio_verify"},
            },
            rules=[
                {"match": {"context.critical": True, "skill": "provision-server"}, "assign_band": "L4"},
            ],
        )
        policy = parse_policy(raw)
        request = SpendRequest(amount=1.00, description="critical server provision")
        result = decide(request, default_authority, policy, skill="provision-server", context={"critical": True})
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_rule_spend_estimate_gt(self, default_authority):
        raw = make_policy_dict(
            bands={
                "L1": {"max_spend": 0.50, "requires_approval": False},
                "L2": {"max_spend": 2.0, "requires_approval": False},
                "L3": {"max_spend": 50.0, "requires_approval": True, "approval_backend": "twilio_verify"},
            },
            rules=[
                {"match": {"spend_estimate_gt": 10.0}, "assign_band": "L3"},
            ],
        )
        policy = parse_policy(raw)
        request = SpendRequest(amount=25.00, description="expensive item")
        result = decide(request, default_authority, policy, skill="deploy-tool")
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_first_matching_rule_wins(self, default_authority):
        raw = make_policy_dict(
            bands={
                "L1": {"max_spend": 0.50, "requires_approval": False},
                "L2": {"max_spend": 2.0, "requires_approval": False},
            },
            rules=[
                {"match": {"skill": "tool-a"}, "assign_band": "L1"},
                {"match": {"skill": "tool-a"}, "assign_band": "L2"},
            ],
        )
        policy = parse_policy(raw)
        request = SpendRequest(amount=1.00, description="first rule should match")
        result = decide(request, default_authority, policy, skill="tool-a")
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_rule_band_under_cap_without_exceeding_session(self, default_authority):
        raw = make_policy_dict(
            bands={
                "L1": {"max_spend": 5.00, "requires_approval": False},
                "L2": {"max_spend": 2.0, "requires_approval": False},
            },
            rules=[
                {"match": {"skill": "bulk-tool"}, "assign_band": "L1"},
            ],
        )
        policy = parse_policy(raw)
        request = SpendRequest(amount=3.00, description="under L1 cap, over default L2 cap")
        result = decide(request, default_authority, policy, skill="bulk-tool")
        assert result.verdict == Verdict.AUTONOMOUS

    def test_default_band_fallback(self, default_authority):
        raw = make_policy_dict(
            bands={
                "L2": {"max_spend": 2.0, "requires_approval": False},
            },
            rules=[
                {"match": {"skill": "some-other-tool"}, "assign_band": "L2"},
            ],
        )
        policy = parse_policy(raw)
        request = SpendRequest(amount=1.50, description="fallback to default")
        result = decide(request, default_authority, policy)
        assert result.verdict == Verdict.AUTONOMOUS


class TestMatchCondition:
    def test_match_skill(self):
        m = MatchCondition(skill="my-tool")
        assert m.matches("my-tool", {}, None)
        assert not m.matches("other-tool", {}, None)

    def test_match_context_flag_default_true(self):
        m = MatchCondition(context_flag="critical")
        assert m.matches(None, {"critical": True}, None)
        assert not m.matches(None, {"critical": False}, None)
        assert not m.matches(None, {}, None)

    def test_match_context_flag_equals_false(self):
        m = MatchCondition(context_flag="dry_run", context_flag_equals=False)
        assert m.matches(None, {"dry_run": False}, None)
        assert not m.matches(None, {"dry_run": True}, None)

    def test_match_spend_estimate_gt(self):
        m = MatchCondition(spend_estimate_gt=10.0)
        assert m.matches(None, {}, 15.0)
        assert not m.matches(None, {}, 10.0)
        assert not m.matches(None, {}, 5.0)

    def test_match_spend_estimate_gt_none(self):
        m = MatchCondition(spend_estimate_gt=10.0)
        assert not m.matches(None, {}, None)

    def test_match_all_conditions(self):
        m = MatchCondition(skill="my-tool", context_flag="critical", spend_estimate_gt=5.0)
        assert m.matches("my-tool", {"critical": True}, 10.0)
        assert not m.matches("my-tool", {"critical": True}, 3.0)
        assert not m.matches("other", {"critical": True}, 10.0)


class TestEscalationConfig:
    def test_valid_config(self):
        ec = EscalationConfig(timeout_seconds=300, on_timeout="retry", retry_count=2)
        ec.validate()

    def test_zero_timeout_invalid(self):
        ec = EscalationConfig(timeout_seconds=0, on_timeout="deny", retry_count=0)
        with pytest.raises(PolicyValidationError, match="timeout_seconds must be positive"):
            ec.validate()

    def test_negative_retry_count_invalid(self):
        ec = EscalationConfig(timeout_seconds=300, on_timeout="deny", retry_count=-1)
        with pytest.raises(PolicyValidationError, match="retry_count must be >= 0"):
            ec.validate()


class TestBandConfig:
    def test_valid_band(self):
        bc = BandConfig(name=Band.L2, max_spend=2.0, requires_approval=False)
        bc.validate()

    def test_requires_approval_with_backend(self):
        bc = BandConfig(name=Band.L3, max_spend=50.0, requires_approval=True, approval_backend="twilio_verify")
        bc.validate()

    def test_requires_approval_without_backend(self):
        bc = BandConfig(name=Band.L3, max_spend=50.0, requires_approval=True)
        with pytest.raises(PolicyValidationError, match="requires_approval=true but no approval_backend"):
            bc.validate()

    def test_unbounded_max_spend(self):
        bc = BandConfig(name=Band.L4, max_spend=None, requires_approval=True, approval_backend="twilio_verify")
        bc.validate()
