"""Tests for Feature 4 — policies.no_self_dealing opt-in directive."""
from __future__ import annotations

import pytest

from custodian.policy.self_dealing import check_self_dealing
from custodian.policy.schema import (
    BandConfig,
    EscalationConfig,
    PoliciesConfig,
    Policy,
)
from custodian.types import Band


def _make_policy(no_self_dealing: bool = False) -> Policy:
    return Policy(
        version="1.0",
        default_band=Band.L2,
        bands={
            Band.L2: BandConfig(name=Band.L2, max_spend=10.0, requires_approval=False),
        },
        rules=[],
        escalation=EscalationConfig(),
        policies=PoliciesConfig(no_self_dealing=no_self_dealing),
    )


class TestSelfDealingBackwardsCompatibility:
    """The default policy (no toggle set) must allow everything."""

    def test_no_self_dealing_disabled_allows_self_deal(self):
        policy = _make_policy(no_self_dealing=False)
        assert check_self_dealing("agent-A", "agent-A", policy) is True

    def test_different_ids_always_allowed(self):
        # Even with the toggle ON, two different IDs are not self-dealing.
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing("agent-A", "agent-B", policy) is True


class TestSelfDealingGating:
    def test_same_ids_with_toggle_on_is_blocked(self):
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing("agent-7", "agent-7", policy) is False

    def test_same_ids_with_toggle_off_is_allowed(self):
        # The operator hasn't enabled the policy — even a clear self-deal
        # is not flagged. The check is opt-in.
        policy = _make_policy(no_self_dealing=False)
        assert check_self_dealing("agent-7", "agent-7", policy) is True


class TestSelfDealingMissingFields:
    def test_empty_requester_bypasses(self):
        """A request without a requester_agent_id is not a self-deal —
        we have no one to call a self-dealer."""
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing("", "agent-7", policy) is True

    def test_empty_recipient_bypasses(self):
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing("agent-7", "", policy) is True

    def test_both_empty_bypasses(self):
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing("", "", policy) is True

    def test_none_ids_bypass(self):
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing(None, None, policy) is True
        assert check_self_dealing("agent-7", None, policy) is True
        assert check_self_dealing(None, "agent-7", policy) is True


class TestSelfDealingEdgeCases:
    def test_case_sensitive(self):
        """Custodian treats agent IDs as opaque strings — 'Agent-A'
        and 'agent-a' are different identities. We preserve that."""
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing("Agent-A", "agent-a", policy) is True
        assert check_self_dealing("agent-a", "agent-a", policy) is False

    def test_whitespace_is_not_stripped(self):
        """Trailing whitespace in an ID is part of the ID. We do not
        silently normalize — that's a job for a different layer."""
        policy = _make_policy(no_self_dealing=True)
        assert check_self_dealing("agent-7", "agent-7 ", policy) is True
        assert check_self_dealing("agent-7 ", "agent-7 ", policy) is False
