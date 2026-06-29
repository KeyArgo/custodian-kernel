"""Tests for Feature 2 — margins opt-in directive."""
from __future__ import annotations

import pytest

from custodian.policy.margin import check_margin
from custodian.policy.schema import (
    BandConfig,
    MarginsConfig,
    Policy,
    EscalationConfig,
)
from custodian.types import Band


def _make_policy(margins: MarginsConfig | None) -> Policy:
    """Build a minimal Policy with the given margins config (or None)."""
    return Policy(
        version="1.0",
        default_band=Band.L2,
        bands={
            Band.L2: BandConfig(
                name=Band.L2, max_spend=100.0, requires_approval=False,
            ),
        },
        rules=[],
        escalation=EscalationConfig(),
        margins=margins,
    )


class TestMarginBackwardsCompatibility:
    """No `margins:` block → the gate never fires."""

    def test_policy_with_no_margins_allows_everything(self):
        policy = _make_policy(margins=None)
        assert check_margin(1.0, 100.0, policy) is True  # massive loss
        assert check_margin(0.0, 0.0, policy) is True
        assert check_margin(-5.0, 10.0, policy) is True

    def test_margins_config_with_both_fields_none_is_a_noop(self):
        # Operator declared the block but left every threshold unset.
        policy = _make_policy(margins=MarginsConfig())
        assert check_margin(10.0, 1000.0, policy) is True

    def test_missing_revenue_or_cost_bypasses_gate(self):
        # Direct call with no revenue/cost must not raise or return False.
        policy = _make_policy(
            margins=MarginsConfig(minimum_margin=1.0, minimum_margin_pct=50.0)
        )
        assert check_margin(None, 10.0, policy) is True
        assert check_margin(10.0, None, policy) is True


class TestMarginAbsoluteThreshold:
    def test_meets_minimum_margin(self):
        policy = _make_policy(margins=MarginsConfig(minimum_margin=10.0))
        assert check_margin(100.0, 90.0, policy) is True   # margin = 10

    def test_exceeds_minimum_margin(self):
        policy = _make_policy(margins=MarginsConfig(minimum_margin=10.0))
        assert check_margin(100.0, 50.0, policy) is True   # margin = 50

    def test_below_minimum_margin_blocks(self):
        policy = _make_policy(margins=MarginsConfig(minimum_margin=10.0))
        assert check_margin(100.0, 95.0, policy) is False  # margin = 5
        assert check_margin(100.0, 100.0, policy) is False # margin = 0
        assert check_margin(100.0, 200.0, policy) is False # margin = -100


class TestMarginPercentThreshold:
    def test_meets_minimum_margin_pct(self):
        policy = _make_policy(margins=MarginsConfig(minimum_margin_pct=20.0))
        assert check_margin(100.0, 80.0, policy) is True  # 20%
        assert check_margin(100.0, 50.0, policy) is True  # 50%

    def test_below_minimum_margin_pct_blocks(self):
        policy = _make_policy(margins=MarginsConfig(minimum_margin_pct=20.0))
        assert check_margin(100.0, 81.0, policy) is False  # 19%
        assert check_margin(50.0, 49.0, policy) is False   # 2%

    def test_zero_revenue_bypasses_pct_check(self):
        """Zero-revenue would div-by-zero; spec says treat as no-op."""
        policy = _make_policy(margins=MarginsConfig(minimum_margin_pct=50.0))
        assert check_margin(0.0, 0.0, policy) is True
        assert check_margin(0.0, 100.0, policy) is True


class TestMarginBothThresholds:
    """When both are set, both must be satisfied (AND semantics)."""

    def test_both_pass(self):
        policy = _make_policy(margins=MarginsConfig(
            minimum_margin=5.0, minimum_margin_pct=20.0,
        ))
        # margin = 30, pct = 30% — both above their minima
        assert check_margin(100.0, 70.0, policy) is True

    def test_absolute_passes_percent_fails(self):
        policy = _make_policy(margins=MarginsConfig(
            minimum_margin=5.0, minimum_margin_pct=20.0,
        ))
        # margin = 10 (passes), pct = 10% (fails)
        assert check_margin(100.0, 90.0, policy) is False

    def test_absolute_fails_percent_passes(self):
        policy = _make_policy(margins=MarginsConfig(
            minimum_margin=50.0, minimum_margin_pct=10.0,
        ))
        # margin = 30 (fails), pct = 30% (passes)
        assert check_margin(100.0, 70.0, policy) is False
