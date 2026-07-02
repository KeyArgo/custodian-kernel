from __future__ import annotations
import functools
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from custodian.types import Band, SpendRequest, Verdict
from custodian.bus import _bus


@dataclass
class GovernedResult:
    """Return value of every @govern-wrapped function."""
    value: Any                    # the wrapped function's actual return value
    verdict: str                  # "autonomous" / "escalation_required" / "denied"
    audit_id: str
    band: str
    amount: float
    description: str
    fn_name: str                  # actual __name__ of the governed function
    elapsed_ms: float
    claim_proof: Optional[str] = None   # "verified" / "contradicted" / "unverifiable"
    ts: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.verdict == "autonomous"

    def receipt(self) -> "GovernedReceipt":
        from custodian.receipt import GovernedReceipt
        return GovernedReceipt.build(
            fn_name=self.fn_name, band=self.band, amount=self.amount,
            description=self.description, verdict=self.verdict,
            reason="", elapsed_ms=self.elapsed_ms, output=self.value,
            claim_proof=self.claim_proof,
        )


class EscalationRequired(Exception):
    def __init__(self, decision, request):
        self.decision = decision
        self.request = request
        super().__init__(f"Escalation required: {decision.reason}")


class KernelDenied(Exception):
    def __init__(self, decision, request):
        self.decision = decision
        self.request = request
        super().__init__(f"Kernel denied: {decision.reason}")


def govern(
    band: str = "L2",
    cap: float = 10.00,
    description: Optional[str] = None,
    cost_usd: float = 0.0,
    policy_path: Optional[str] = None,
    state_dir: Optional[str] = None,
    verify_output: bool = False,
    raise_on_escalation: bool = True,
):
    """
    Decorator that wraps any callable with kernel authority enforcement.

    Usage:
        @govern(band="L2", cap=50.00)
        def charge_customer(amount: float, customer_id: str) -> dict:
            return stripe_client.charge(amount=amount, customer=customer_id)

        result = charge_customer(85.00, "cus_123")
        # result.ok == True if within band
        # raises EscalationRequired if amount > cap
        # raises KernelDenied if kill switch is engaged

    The caller never invokes the kernel explicitly.
    The kernel is the call path.
    """
    def decorator(fn: Callable) -> Callable:
        _desc = description or fn.__doc__ or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> GovernedResult:
            # Extract amount from kwargs first, then first numeric positional arg
            amount = float(kwargs.get("amount", cost_usd))
            if amount == 0.0 and args:
                for arg in args:
                    if isinstance(arg, (int, float)) and arg > 0:
                        amount = float(arg)
                        break

            request = SpendRequest(amount=amount, description=_desc)
            audit_id = str(uuid.uuid4())[:8]

            # Load policy + state lazily (not at decoration time)
            decision = _evaluate(request, band, cap, policy_path, state_dir)

            if decision.verdict == Verdict.DENIED:
                _bus.emit("kernel_denied", {
                    "audit_id": audit_id, "amount": amount, "reason": decision.reason
                })
                if raise_on_escalation:
                    raise KernelDenied(decision, request)
                return GovernedResult(value=None, verdict="denied", audit_id=audit_id,
                                      band=band, amount=amount, description=_desc,
                                      fn_name=fn.__name__, elapsed_ms=0.0)

            if decision.verdict == Verdict.ESCALATION_REQUIRED:
                _bus.emit("escalation_required", {
                    "audit_id": audit_id, "amount": amount,
                    "reason": decision.reason, "request": request
                })
                if raise_on_escalation:
                    raise EscalationRequired(decision, request)
                return GovernedResult(value=None, verdict="escalation_required", audit_id=audit_id,
                                      band=band, amount=amount, description=_desc,
                                      fn_name=fn.__name__, elapsed_ms=0.0)

            # AUTONOMOUS — execute
            _bus.emit("pre_execute", {"audit_id": audit_id, "amount": amount, "fn": fn.__name__})
            t0 = time.monotonic()
            value = fn(*args, **kwargs)
            elapsed_ms = (time.monotonic() - t0) * 1000

            # Optional output claim verification
            claim_proof = None
            if verify_output and isinstance(value, dict):
                claim_proof = _verify_output(fn.__name__, amount, value, audit_id)

            result = GovernedResult(
                value=value, verdict="autonomous", audit_id=audit_id,
                band=band, amount=amount, description=_desc,
                fn_name=fn.__name__, elapsed_ms=elapsed_ms, claim_proof=claim_proof,
            )
            _bus.emit("post_execute", {"audit_id": audit_id, "result": result})
            return result

        wrapper._governed = True
        wrapper._band = band
        wrapper._cap = cap
        return wrapper

    return decorator


def _evaluate(request, band, cap, policy_path, state_dir):
    """Internal: load policy/state and call decide(). Never raises."""
    from custodian.policy import load_policy
    from custodian.policy.evaluator import decide
    from custodian.config import CustodianConfig
    from custodian.types import AuthorityState
    import json
    from pathlib import Path

    cfg = CustodianConfig.from_env()

    # When policy_path is explicitly set (either by caller or env), load it.
    # Otherwise use the decorator's own cap parameter to drive the policy.
    # This preserves backward compat with the existing kernel CLI flow while
    # letting @govern work standalone without requiring a policy file on disk.
    if policy_path:
        _policy_path = Path(policy_path)
        try:
            policy = load_policy(_policy_path)
        except Exception:
            policy = _minimal_policy(band, cap)
    elif cfg.policy_path and Path(cfg.policy_path).exists():
        try:
            policy = load_policy(Path(cfg.policy_path))
        except Exception:
            policy = _minimal_policy(band, cap)
    else:
        # No policy file on disk: honor the decorator's cap directly
        policy = _minimal_policy(band, cap)

    _state_dir = Path(state_dir) if state_dir else cfg.state_dir
    state_file = _state_dir / "authority.json"
    if state_file.exists():
        try:
            state = AuthorityState.from_dict(json.loads(state_file.read_text()))
        except Exception:
            state = AuthorityState(band=Band(band), per_action_cap=cap, session_cap=cap * 10)
    else:
        state = AuthorityState(band=Band(band), per_action_cap=cap, session_cap=cap * 10)

    killed = False
    ks_file = _state_dir / "kill_switch.json"
    if ks_file.exists():
        try:
            killed = bool(json.loads(ks_file.read_text()).get("killed", False))
        except Exception:
            killed = True  # fail closed: corrupted kill switch = treated as killed

    return decide(request, state, policy, killed=killed)


def _minimal_policy(band: str, cap: float):
    """Synthesize a minimal in-memory policy when no policy file exists."""
    from custodian.policy.schema import Policy, BandConfig, EscalationConfig
    from custodian.types import Band

    bands = {
        Band(b): BandConfig(
            name=Band(b),
            max_spend=cap,
            requires_approval=False,
        )
        for b in ("L0", "L1", "L2", "L3", "L4")
    }
    policy = Policy(
        version="1.0",
        default_band=Band(band),
        bands=bands,
        rules=[],
        escalation=EscalationConfig(),
    )
    return policy


def _verify_output(fn_name, amount, value, audit_id):
    """Verify the function output against the ledger. Returns claim status string."""
    try:
        from custodian.packs.base import verify_claims, Claim
        claims = [Claim(
            id=audit_id,
            statement=f"{fn_name} returned amount={amount}",
            customer_quote=str(value),
            ledger_path="result.amount",
            relation="eq",
            asserted=amount,
        )]
        scope = {"result": {"amount": value.get("amount", amount)}}
        results = verify_claims(claims, scope)
        return results[0].status.value if results else None
    except Exception:
        return None
