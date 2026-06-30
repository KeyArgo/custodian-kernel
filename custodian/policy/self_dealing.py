"""Feature 4 — Self-dealing detector.

Opt-in directive: a policy may declare `policies: { no_self_dealing: true }`.
When set, check_self_dealing() returns False if the same agent is both
the requester and the recipient of the request — i.e. the agent is
approving its own spend, the very pattern Custodian was built to prevent.

Design notes:
    * Truly opt-in. If the policy doesn't set `policies.no_self_dealing` (or
      if the request carries no requester/recipient IDs), the check is a
      no-op and returns True.

    * Both IDs must be non-empty strings AND equal for the gate to fire.
      An empty string in either field means "not set" and the gate is
      bypassed.

    * This is a deliberately minimal check — it lives in its own module
      so future heuristics (shared wallet, graph analysis, etc.) can be
      slotted in without touching the evaluator's integration surface.

    * The evaluator wraps every new check in a try/except so a malformed
      or missing directive is logged and the decision continues through
      the existing cap checks. This function is kept intentionally simple
      so that try/except is almost never triggered.
"""
from __future__ import annotations

from typing import Optional

from custodian.policy.schema import Policy


def check_self_dealing(
    requester_id: Optional[str],
    recipient_id: Optional[str],
    policy: Policy,
) -> bool:
    """Return True if the request is *not* self-dealing.

    The check only fires when ALL of these conditions are met:
        1. policy.policies is not None (the `policies:` block exists)
        2. policy.policies.no_self_dealing is True (the toggle is on)
        3. both requester_id and recipient_id are non-empty strings
        4. requester_id == recipient_id

    If any condition is False, the function returns True (the request is
    considered safe from a self-dealing perspective), and the evaluator
    moves on to the next check.
    """
    if policy.policies is None:
        return True
    if not policy.policies.no_self_dealing:
        return True
    if not requester_id or not recipient_id:
        return True
    return requester_id != recipient_id
