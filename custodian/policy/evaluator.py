"""The policy evaluator: given a SpendRequest and current AuthorityState,
decide what happens.

This function is the formalization of the logic that already lives,
hardcoded, in spend.py today -- over_cap / over_session -> escalate;
otherwise -> autonomous. Wrapping it here doesn't change the verified
behavior, it makes the same decision configurable per-policy instead of
hardcoded to one set of numbers, and makes the decision itself a typed,
testable, reusable object instead of print statements and an exit code.
"""
from __future__ import annotations

from typing import Optional

from custodian.policy.schema import Policy
from custodian.types import AuthorityState, Band, Decision, SpendRequest, Verdict


def decide(
    request: SpendRequest,
    state: AuthorityState,
    policy: Policy,
    *,
    skill: Optional[str] = None,
    context: Optional[dict] = None,
    killed: bool = False,
) -> Decision:
    context = context or {}

    if killed:
        # Checked first, before any band/cap logic, and short-circuits
        # everything else -- the kill switch overrides every other rule,
        # with no band, amount, or context that can route around it. This
        # is an operator-only override; nothing in this function can set
        # `killed` itself, only a caller that already consulted a real
        # kill-switch state can pass it in.
        return Decision(
            verdict=Verdict.DENIED,
            request=request,
            reason="kill switch is engaged -- all requests denied until an operator releases it",
            band=policy.default_band,
        )
    band = policy.band_for(skill, context, request.amount)
    band_cfg = policy.bands.get(band)

    if band_cfg is None:
        # Policy validation should make this unreachable, but a Decision
        # must never silently default to permissive behavior if it somehow
        # does happen -- fail closed.
        return Decision(
            verdict=Verdict.ESCALATION_REQUIRED,
            request=request,
            reason=f"no band configuration found for '{band}' -- failing closed",
            band=band,
        )

    over_band_cap = band_cfg.max_spend is not None and request.amount > band_cfg.max_spend
    over_session_cap = request.amount > state.remaining_session_budget()

    if band_cfg.requires_approval or over_band_cap or over_session_cap:
        reasons = []
        if band_cfg.requires_approval:
            reasons.append(f"band {band.value} always requires approval")
        if over_band_cap:
            reasons.append(
                f"${request.amount:.2f} exceeds band {band.value} max_spend ${band_cfg.max_spend:.2f}"
            )
        if over_session_cap:
            reasons.append(
                f"${request.amount:.2f} exceeds remaining session budget "
                f"${state.remaining_session_budget():.2f}"
            )
        return Decision(
            verdict=Verdict.ESCALATION_REQUIRED,
            request=request,
            reason="; ".join(reasons),
            band=band,
        )

    return Decision(
        verdict=Verdict.AUTONOMOUS,
        request=request,
        reason=(
            f"${request.amount:.2f} within band {band.value} "
            f"(cap ${band_cfg.max_spend if band_cfg.max_spend is not None else float('inf'):.2f}, "
            f"remaining ${state.remaining_session_budget():.2f})"
        ),
        band=band,
    )
