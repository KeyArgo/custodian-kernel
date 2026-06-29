"""The generic triage engine. Pack-agnostic: it runs any PolicyPack's
envelope through the shared verifier, the pack's deterministic adapter, and
finally the real kernel. Adding a new business operation (purchasing,
receivables) means writing a new PolicyPack -- the engine never changes.
"""
from __future__ import annotations

import copy

from custodian.packs.base import (
    ClaimStatus,
    Envelope,
    PolicyPack,
    TriageResult,
    verify_claims,
)
from custodian.policy.schema import Policy
from custodian.types import AuthorityState, SpendRequest
try:
    from custodian.policy.enforcer import decide
except ImportError:
    from custodian.policy.evaluator import decide


def triage(
    pack: PolicyPack,
    envelope: Envelope,
    kernel_policy: Policy,
    state: AuthorityState,
    *,
    killed: bool = False,
) -> TriageResult:
    """Run one case end to end.

    1. verifier checks every claim against the pack's ground-truth ledger
    2. pack adapter derives a disposition (deterministic policy-as-code)
    3. kernel decides authority -- refunds always land on a band that
       requires a human, so money never moves on the agent's say-so.
    """
    scope = pack.ledger_scope(envelope)
    verify_claims(envelope.claims, scope)
    contradictions = [c for c in envelope.claims if c.status == ClaimStatus.CONTRADICTED]

    disposition, reasons, why_not_a_script = pack.adapter(envelope)

    request = SpendRequest(amount=envelope.amount, description=envelope.agent_summary)
    decision = decide(
        request,
        state,
        kernel_policy,
        skill=pack.requested_action,
        context={"disposition": disposition},
        killed=killed,
    )

    # The single honest outcome: money moves on its own ONLY when the domain
    # adapter blessed this disposition as autonomy-eligible AND the kernel band
    # permits the amount. Two independent gates; both must say yes. This is why
    # the kernel saying "the amount is fine" can never, by itself, release a
    # payment the domain layer flagged.
    final_action = _final_action(
        disposition, decision.verdict.value, pack.autonomous_dispositions
    )

    return TriageResult(
        envelope=envelope,
        contradictions=contradictions,
        adapter_disposition=disposition,
        adapter_reasons=reasons,
        why_not_a_script=why_not_a_script,
        kernel_verdict=decision.verdict.value,
        kernel_reason=decision.reason,
        final_action=final_action,
        ledger_scope=scope,
    )


def _final_action(disposition: str, kernel_verdict: str, autonomous_dispositions) -> str:
    if kernel_verdict == "denied":
        return "blocked_kill_switch"
    eligible = disposition in autonomous_dispositions
    if eligible and kernel_verdict == "autonomous":
        return "executed_autonomously"
    if eligible and kernel_verdict == "escalation_required":
        # domain is happy, but the amount/band needs a human signature
        return "pending_human_approval"
    # domain did not bless autonomy -> a human reviews, regardless of the band
    return "needs_human_review"


def replay_with_policy_change(
    pack: PolicyPack,
    envelope: Envelope,
    kernel_policy: Policy,
    state: AuthorityState,
    rule_overrides: dict,
) -> tuple[TriageResult, TriageResult]:
    """Policy-diff replay: run the SAME case + SAME envelope twice -- once
    with the pack's current domain rules, once with one rule changed (e.g.
    return window 30 -> 45 days) -- and return both results so the dashboard
    can show the disposition flip live.

    This is what proves it's a reusable engine, not a hardcoded demo: a
    non-engineer (legal/finance/ops) changes one policy value and instantly
    sees how every pending decision would re-resolve, with no model retrain
    and no code change.
    """
    before = triage(pack, copy.deepcopy(envelope), kernel_policy, state)

    saved = dict(pack.rules)
    try:
        pack.rules = {**pack.rules, **rule_overrides}
        after = triage(pack, copy.deepcopy(envelope), kernel_policy, state)
    finally:
        pack.rules = saved

    return before, after
