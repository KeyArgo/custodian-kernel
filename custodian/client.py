"""Value-free governance client — API-boundary that never sees secrets.

Pattern adapted from cyberware's **value-free protocol** (exod.py / govd.py):
only the *schema* of inputs crosses the governance wire — skill name, perk
name, and variable *keys* (never their values, secrets, or source code).
Values are injected by a local blessed executor after the kernel authorizes.

Usage::

    from custodian.client import ValueFreeClient

    client = ValueFreeClient(state_dir="/tmp/custodian-state")

    plan = client.authorize(
        skill="stripe-charges",
        perk="charge_customer",
        var_keys={"amount", "customer_id"},   # keys only
    )

    if plan.verdict == "authorized":
        # Local executor injects real values, then calls plan.blessed_func()
        result = plan.execute({"amount": 85.00, "customer_id": "cus_123"})
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

log = logging.getLogger(__name__)


@dataclass
class ValueFreePlan:
    """An authorized execution plan — kernel says YES, local executor says HOW.

    The plan carries a SHA-256 *fingerprint* covering the skill, perk, and
    var_keys that were authorized.  Any attempt to call it with a different
    set of keys (or a different skill/perk) will be rejected.
    """
    skill: str
    perk: str
    var_keys: Set[str]
    band: str
    cap: float
    fingerprint: str          # SHA-256 over canonical skill+perk+var_keys
    fn: Optional[Callable] = None  # Optional blessed function (if callable is known)
    ts: float = field(default_factory=time.time)
    audit_id: str = ""

    def validate_keys(self, provided: Dict[str, Any]) -> bool:
        """Return True if *provided* keys match the authorized var_keys exactly."""
        return set(provided.keys()) == self.var_keys

    def execute(self, values: Dict[str, Any]) -> Any:
        """Execute the blessed function with the provided values.

        Raises KeyError if the provided keys don't match the authorized set.
        """
        if self.fn is None:
            raise RuntimeError(
                f"ValueFreePlan for {self.skill}/{self.perk} has no bound function; "
                "use the internal executor path to inject values."
            )
        if not self.validate_keys(values):
            raise ValueError(
                f"Unauthorized keys: expected {self.var_keys}, got {set(values.keys())}"
            )
        return self.fn(**values)


class ValueFreeClient:
    """Client-side interface for the value-free protocol.

    Accepts only schema (skill, perk, var_keys) — never values or secrets —
    and returns an authorized plan that the local executor uses to bind and
    run the actual function.

    Mirrors cyberware's value-free protocol (exod.py / govd.py): the governance
    plane never sees secrets, code, or values; it only authorizes the schema.
    """

    def __init__(self, state_dir: Optional[str] = None, cap: float = 10.00):
        self.state_dir = state_dir
        self.cap = cap

    @staticmethod
    def _fingerprint(skill: str, perk: str, var_keys: Set[str]) -> str:
        """SHA-256 over canonical skill+perk+var_keys."""
        payload = json.dumps({"s": skill, "p": perk, "k": sorted(var_keys)}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def authorize(
        self,
        skill: str,
        perk: str,
        var_keys: Set[str],
        band: str = "L2",
    ) -> ValueFreePlan:
        """Request authorization for a schema-bound execution plan.

        Args:
            skill: Skill name (e.g. "stripe-charges").
            perk: Perk name within the skill (e.g. "charge_customer").
            var_keys: Set of variable *names* — never values.
            band: Governance band for the request.

        Returns:
            ValueFreePlan — the kernel's authorized execution template.
        """
        fp = self._fingerprint(skill, perk, var_keys)
        audit_id = f"{skill}/{perk}/{str(uuid.uuid4())[:8]}"

        # Evaluate kernel policy — amount is always zero because we have
        # no values yet; the exec-path carries the amount.
        from custodian.types import SpendRequest, Verdict
        from custodian.govern import _evaluate

        request = SpendRequest(amount=0.0, description=f"value-free:{skill}/{perk}")
        decision = _evaluate(request, band, self.cap, None, self.state_dir)

        if decision.verdict != Verdict.AUTONOMOUS:
            log.warning(
                "ValueFreeClient: kernel denied value-free plan for %s/%s: %s",
                skill, perk, decision.reason,
            )
            raise KernelDenied(
                verdict=decision.verdict.value,
                reason=decision.reason,
                audit_id=audit_id,
            )

        plan = ValueFreePlan(
            skill=skill,
            perk=perk,
            var_keys=var_keys,
            band=band,
            cap=self.cap,
            fingerprint=fp,
            audit_id=audit_id,
        )
        return plan


class KernelDenied(Exception):
    """Raised when the value-free kernel denies authorization."""

    def __init__(self, verdict: str, reason: str, audit_id: str):
        self.verdict = verdict
        self.reason = reason
        self.audit_id = audit_id
        super().__init__(f"Kernel denied value-free plan: {reason} ({audit_id})")


@dataclass
class ValueFreeResult:
    """Result of executing a value-free plan."""
    plan: ValueFreePlan
    value: Any
    verdict: str
    elapsed_ms: float
    audit_id: str
    ts: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.verdict == "autonomous"
