"""Feature 2 — Margin gate.

Opt-in directive: a policy may declare a `margins:` block with one or
both of:
    margins:
      minimum_margin: 0.10       # absolute dollars
      minimum_margin_pct: 20     # percent of revenue

When a request carries revenue/cost, check_margin() verifies the
resulting margin meets at least the configured minimum. If not, the
request is denied with reason "margin_below_threshold".

Design notes:
    * Truly opt-in. A Policy that doesn't set `margins:` (i.e. it
      has no MarginsConfig) — or sets MarginsConfig with both fields
      left as None — has no margin gate. The evaluator only calls
      this function when revenue and cost are present, so a request
      without those fields also bypasses the check.

    * The spec calls out "AND revenue > 0 and revenue > 0" — that's
      a typo in the prompt, but the intent is clear: a zero-revenue
      or negative-revenue request is meaningless to gate, so we
      return True (allow) in that case. A negative-cost or negative-
      revenue input is a programming error upstream, but we still
      return True (fail-open) rather than crash — and let the
      validate()-level checks catch the obvious bad policy.

    * Both fields are checked. The first one to fail returns False
      and short-circuits; the reason field in the Decision tells
      the operator which constraint tripped.
"""
from __future__ import annotations

from typing import Optional

from custodian.policy.schema import MarginsConfig, Policy


def check_margin(
    revenue: Optional[float],
    cost: Optional[float],
    policy: Policy,
) -> bool:
    """Return True if the request's margin meets the configured minimum,
    False if it falls below.

    The policy-level guard is: if `policy.margins is None` or both
    thresholds are None, the gate is silent and we return True. This
    is what preserves backward compatibility with policies that don't
    opt in.
    """
    if policy.margins is None:
        return True
    margins: MarginsConfig = policy.margins
    if margins.minimum_margin is None and margins.minimum_margin_pct is None:
        return True

    # Treat "no revenue/cost provided" as a request that doesn't engage
    # the gate. The evaluator only calls us when both are present, so
    # this branch is mostly defensive.
    if revenue is None or cost is None:
        return True

    # The "revenue > 0" guard prevents div-by-zero on the pct check
    # and stops the gate from spuriously denying a refund or a pure
    # cost with zero revenue.
    if revenue <= 0:
        return True

    margin = revenue - cost
    if margins.minimum_margin is not None and margin < margins.minimum_margin:
        return False
    if margins.minimum_margin_pct is not None:
        margin_pct = (margin / revenue) * 100.0
        if margin_pct < margins.minimum_margin_pct:
            return False
    return True
