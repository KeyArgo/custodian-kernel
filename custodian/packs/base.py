"""Policy-pack layer: one kernel, many packs.

The kernel (custodian.policy.evaluator.decide) decides authority: given an
amount, a band, and caps, it says AUTONOMOUS / ESCALATION_REQUIRED / DENIED.
It knows nothing about refunds, purchasing, or vendors -- and it must stay
that way. A *policy pack* is the domain layer that sits on top: it turns a
messy real-world input (a customer email) into a structured, verifiable
request the kernel can act on, and frames the human escalation when one is
required.

The flow is three independent layers, and that independence is the whole
point:

    messy input
        │
        ▼
   [ AI judgment ]  -> Envelope        (the agent: reads the world, NEVER decides money)
        │
        ▼
   [ verifier ]    -> ClaimStatus      (deterministic: checks every claim vs ground truth)
        │
        ▼
   [ adapter ]     -> Disposition      (deterministic policy-as-code: window, exceptions, abuse)
        │
        ▼
   [ kernel ]      -> Decision         (deterministic: bands/caps; refunds always escalate)

The agent can be wrong, or even lie, and money still cannot move incorrectly:
a contradicted claim is caught by the verifier before the adapter ever trusts
it, and the kernel still forces a human signature on anything that touches
money. No single layer is load-bearing for trust on its own.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ClaimStatus(str, Enum):
    VERIFIED = "verified"          # ground truth supports the customer's assertion
    CONTRADICTED = "contradicted"  # ground truth directly refutes it  <-- the lie-catch
    UNVERIFIABLE = "unverifiable"  # we have no ground-truth field to check it against
    PENDING = "pending"            # not yet checked


@dataclass
class EvidenceSpan:
    """A literal quote, with where it came from. The dashboard shows these
    verbatim so judgment is never 'trust me' -- it's 'here is the exact
    sentence I relied on.'"""
    source: str   # "email" | "policy" | "ledger"
    quote: str
    locator: str = ""  # e.g. "refund-policy.md:exceptions.defect"


@dataclass
class Claim:
    """A factual assertion in the customer's message that bears on the
    decision. The agent extracts it (statement + the literal customer quote);
    the deterministic verifier resolves `ledger_path` against ground truth and
    fills in `actual` + `status`. The agent does not get to mark its own
    homework."""
    id: str
    statement: str
    customer_quote: str
    ledger_path: str           # dotted path resolved within the case's ledger scope
    relation: str              # eq | neq | gt | lt | gte | lte | exists | absent
    asserted: Any = None
    actual: Any = None
    status: ClaimStatus = ClaimStatus.PENDING

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        return cls(
            id=d["id"],
            statement=d["statement"],
            customer_quote=d.get("customer_quote", ""),
            ledger_path=d["ledger_path"],
            relation=d["relation"],
            asserted=d.get("asserted"),
        )


@dataclass
class Envelope:
    """The agent's structured output. Note what is NOT here: any authority to
    move money. The agent recommends; it never approves. `recommended_*` is
    advisory and is independently re-derived by the deterministic adapter."""
    case_id: str
    customer_id: str
    order_id: str
    amount: float
    requested_action: str           # e.g. "refund.create"
    claims: list[Claim]
    policy_clauses_cited: list[EvidenceSpan]
    recommended_disposition: str    # advisory only
    confidence: float
    agent_summary: str

    @classmethod
    def from_dict(cls, d: dict) -> "Envelope":
        return cls(
            case_id=d["case_id"],
            customer_id=d["customer_id"],
            order_id=d["order_id"],
            amount=float(d["amount"]),
            requested_action=d.get("requested_action", "refund.create"),
            claims=[Claim.from_dict(c) for c in d.get("claims", [])],
            policy_clauses_cited=[EvidenceSpan(**e) for e in d.get("policy_clauses_cited", [])],
            recommended_disposition=d.get("recommended_disposition", "escalate_ambiguous"),
            confidence=float(d.get("confidence", 0.0)),
            agent_summary=d.get("agent_summary", ""),
        )


def _resolve(obj: Any, dotted: str) -> tuple[Any, bool]:
    """Resolve a dotted path against nested dicts. Returns (value, found)."""
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None, False
    return cur, True


def _compare(actual: Any, relation: str, asserted: Any) -> bool:
    if relation == "exists":
        return actual is not None
    if relation == "absent":
        return actual is None
    if actual is None:
        return False
    try:
        if relation == "eq":
            return actual == asserted
        if relation == "neq":
            return actual != asserted
        if relation == "gt":
            return actual > asserted
        if relation == "lt":
            return actual < asserted
        if relation == "gte":
            return actual >= asserted
        if relation == "lte":
            return actual <= asserted
    except TypeError:
        return False
    raise ValueError(f"unknown relation: {relation}")


def verify_claims(claims: list[Claim], ledger_scope: dict) -> list[Claim]:
    """The lie-catcher. Deterministic, zero-AI. For each claim, resolve the
    ground-truth field and decide whether the customer's assertion holds.

    This is the layer that makes the platform trustworthy: the agent's words
    are never taken as fact. A claim is only VERIFIED if real data backs it,
    and a claim that ground truth refutes is flagged CONTRADICTED -- which the
    adapter then refuses to let a positive recommendation stand on.
    """
    for c in claims:
        actual, found = _resolve(ledger_scope, c.ledger_path)
        c.actual = actual
        # An unresolvable path is UNVERIFIABLE only for value comparisons
        # (eq/gt/...), where there is genuinely nothing to compare against.
        # For presence relations the absence of the path IS the ground truth:
        # an "exists" claim on a missing field is refuted by that absence
        # (CONTRADICTED, not merely unverifiable -- otherwise a fabricated
        # "authorization exists" claim slips past the lie-catch), and an
        # "absent" claim on a missing field is confirmed by it.
        if not found and c.relation not in ("absent", "exists"):
            c.status = ClaimStatus.UNVERIFIABLE
            continue
        holds = _compare(actual, c.relation, c.asserted)
        c.status = ClaimStatus.VERIFIED if holds else ClaimStatus.CONTRADICTED
    return claims


@dataclass
class TriageResult:
    """Everything the dashboard reasoning panel needs, plus the kernel's
    authority decision. Deliberately separates 'AI assessment' (envelope,
    adapter disposition, reasons) from 'kernel authority outcome' (decision)
    so a viewer can never confuse a recommendation with an executed action."""
    envelope: Envelope
    contradictions: list[Claim]
    adapter_disposition: str
    adapter_reasons: list[str]
    why_not_a_script: str
    kernel_verdict: str
    kernel_reason: str
    final_action: str = ""   # what actually happens to money (see engine.triage)
    ledger_scope: dict = field(default_factory=dict)

    def to_panel(self) -> dict:
        return {
            "case_id": self.envelope.case_id,
            "final_action": self.final_action,
            "amount": self.envelope.amount,
            "agent_summary": self.envelope.agent_summary,
            "agent_confidence": self.envelope.confidence,
            "agent_recommended": self.envelope.recommended_disposition,
            "claims": [
                {
                    "statement": c.statement,
                    "customer_quote": c.customer_quote,
                    "ledger_path": c.ledger_path,
                    "relation": c.relation,
                    "asserted": c.asserted,
                    "actual": c.actual,
                    "status": c.status.value,
                }
                for c in self.envelope.claims
            ],
            "policy_clauses_cited": [
                {"quote": e.quote, "locator": e.locator} for e in self.envelope.policy_clauses_cited
            ],
            "contradiction_count": len(self.contradictions),
            "adapter_disposition": self.adapter_disposition,
            "adapter_reasons": self.adapter_reasons,
            "why_not_a_script": self.why_not_a_script,
            "kernel_verdict": self.kernel_verdict,
            "kernel_reason": self.kernel_reason,
        }


class PolicyPack:
    """A pack = a domain policy + an account ledger + a decision adapter.

    Subclasses must implement `adapter`, which turns a verified envelope into
    a (disposition, reasons, why_not_a_script) tuple. Everything else -- claim
    verification, kernel hand-off -- is shared and lives in the engine.
    """
    name: str = "base"
    requested_action: str = "noop"
    # Which adapter dispositions are even ELIGIBLE to execute without a human,
    # IF the kernel band also permits the amount. Empty by default -- a pack
    # opts in explicitly. Refunds leave this empty (nothing auto-executes);
    # purchasing allows only its clean auto_pay disposition.
    autonomous_dispositions: frozenset = frozenset()

    def ledger_scope(self, envelope: Envelope) -> dict:
        raise NotImplementedError

    def adapter(self, envelope: Envelope) -> tuple[str, list[str], str]:
        raise NotImplementedError
