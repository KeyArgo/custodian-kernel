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

import logging
from typing import Optional

from custodian.policy.schema import Policy
from custodian.types import AuthorityState, Band, Decision, SpendRequest, Verdict

log = logging.getLogger(__name__)


def decide(
    request: SpendRequest,
    state: AuthorityState,
    policy: Policy,
    *,
    skill: Optional[str] = None,
    context: Optional[dict] = None,
    killed: bool = False,
    ledger_storage = None,
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

    # --- Opt-in check: auto-downgrade after task (band_after_task) ---
    # Must run BEFORE cap checks because the downgrade might lower the
    # effective band, and we want the cap check to use the downgraded band.
    # Only runs if band_cfg.band_after_task is set.
    effective_band = band
    if band_cfg.band_after_task is not None:
        try:
            from custodian.policy.autorank import apply_autorank
            effective_band = apply_autorank(state, band, band_cfg, request)
            if effective_band != band:
                band_cfg = policy.bands.get(effective_band) or band_cfg
        except Exception as e:
            log.warning("autorank check failed, continuing: %s", e)

    # --- Opt-in check: 24-hour daily envelope ---
    if band_cfg.daily_envelope is not None and ledger_storage is not None:
        try:
            from custodian.policy.envelope import check_envelope
            if not check_envelope(ledger_storage, band_cfg, request.amount):
                return Decision(
                    verdict=Verdict.ESCALATION_REQUIRED,
                    request=request,
                    reason=(
                        f"${request.amount:.2f} would exceed band {band_cfg.name.value} "
                        f"daily_envelope ${band_cfg.daily_envelope:.2f}"
                    ),
                    band=effective_band,
                )
        except Exception as e:
            log.warning("envelope check failed, continuing: %s", e)

    # --- Opt-in check: margin gate ---
    # Only runs if the request has revenue and cost fields AND the policy
    # has a margins: directive. Requests without margin info skip this.
    request_revenue = getattr(request, "revenue", None)
    request_cost = getattr(request, "cost", None)
    if (
        policy.margins is not None
        and request_revenue is not None
        and request_cost is not None
    ):
        try:
            from custodian.policy.margin import check_margin
            if not check_margin(request_revenue, request_cost, policy):
                return Decision(
                    verdict=Verdict.DENIED,
                    request=request,
                    reason=(
                        f"margin ${request_revenue - request_cost:.2f} below "
                        f"minimum_margin ${policy.margins.minimum_margin or 0:.2f} "
                        f"or minimum_margin_pct {policy.margins.minimum_margin_pct or 0:.1f}%"
                    ),
                    band=effective_band,
                )
        except Exception as e:
            log.warning("margin check failed, continuing: %s", e)

    # --- Opt-in check: self-dealing detector ---
    if policy.policies is not None and policy.policies.no_self_dealing:
        try:
            from custodian.policy.self_dealing import check_self_dealing
            requester = getattr(request, "requester_agent_id", None)
            recipient = getattr(request, "recipient_agent_id", None)
            if not check_self_dealing(requester, recipient, policy):
                return Decision(
                    verdict=Verdict.DENIED,
                    request=request,
                    reason="self_dealing_detected: requester and recipient are the same agent",
                    band=effective_band,
                )
        except Exception as e:
            log.warning("self_dealing check failed, continuing: %s", e)

    over_band_cap = band_cfg.max_spend is not None and request.amount > band_cfg.max_spend
    over_session_cap = request.amount > state.remaining_session_budget()

    if band_cfg.requires_approval or over_band_cap or over_session_cap:
        reasons = []
        if band_cfg.requires_approval:
            reasons.append(f"band {effective_band.value} always requires approval")
        if over_band_cap:
            reasons.append(
                f"${request.amount:.2f} exceeds band {effective_band.value} max_spend ${band_cfg.max_spend:.2f}"
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
            band=effective_band,
        )

    return Decision(
        verdict=Verdict.AUTONOMOUS,
        request=request,
        reason=(
            f"${request.amount:.2f} within band {effective_band.value} "
            f"(cap ${band_cfg.max_spend if band_cfg.max_spend is not None else float('inf'):.2f}, "
            f"remaining ${state.remaining_session_budget():.2f})"
        ),
        band=effective_band,
    )
