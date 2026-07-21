"""The kernel's independent decision gate, shared by every governed call
path -- CustodianTool.invoke() (skill scripts), custodian.executor.service
(the delegated executor), and custodian.inference.router (LLM calls).

Extracted from what used to be CustodianTool._kernel_decide's private body
so a fix to the state/policy-loading logic (or a bug in it) can't silently
diverge between call paths -- this codebase has already been adversarially
reviewed for exactly that class of two-tier bug elsewhere this session.
"""
from __future__ import annotations

import json
from pathlib import Path


def kernel_gate(amount: float, *, action: str, state_dir: Path,
                fallback_band: str = "L2") -> dict:
    """Consult the kernel policy engine for a real-money or real-cost action.

    `amount` is the real requested spend for this call -- never a static
    declared default. `action` is a human-readable label for the decision's
    description/audit trail (e.g. "tool:stripe-spend" or "inference:openrouter").
    `state_dir` is the caller's resolved state directory (e.g.
    custodian.tools.registry._state_dir()) -- required, not defaulted here,
    so this module has no dependency on where any particular caller keeps
    its state. `fallback_band` is only used in the band field of the
    exception path below, so a caller with a known declared band (e.g. an
    L3 tool) doesn't get misreported as L2 if the gate itself errors.

    Never raises: any failure to load state/policy escalates fail-closed,
    same posture as every other kernel gate in this codebase.
    """
    from custodian.policy import load_policy
    from custodian.policy.evaluator import decide
    from custodian.types import AuthorityState, Band, SpendRequest

    try:
        state_path = state_dir / "authority.json"
        if state_path.exists():
            state = AuthorityState.from_dict(json.loads(state_path.read_text()))
        else:
            state = AuthorityState(band=Band.L2, per_action_cap=250.0, session_cap=1000.0)

        ks_path = state_dir / "kill_switch.json"
        killed = False
        if ks_path.exists():
            try:
                killed = bool(json.loads(ks_path.read_text()).get("killed", False))
            except Exception:
                killed = True  # corrupted kill switch file = treat as killed

        policy_path = state_dir / "policy.yaml"
        if not policy_path.exists():
            here = Path(__file__).resolve().parent.parent
            policy_path = here / "policy" / "presets" / "default.yaml"
        policy = load_policy(policy_path)

        request = SpendRequest(amount=amount, description=action)
        decision = decide(request, state, policy, skill=action, killed=killed)
        return {
            "verdict": decision.verdict.value,
            "reason": decision.reason,
            "band": decision.band.value,
        }
    except Exception as exc:
        return {
            "verdict": "escalation_required",
            "reason": (
                "kernel decision could not be evaluated "
                f"({type(exc).__name__}: {exc}) -- escalating fail-closed"
            ),
            "band": fallback_band,
        }
