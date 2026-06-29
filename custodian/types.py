"""Core data types shared across the policy engine, backends, and CLI.

These mirror the field names already used by the proven spend.py/approve.py/
_core.py scripts in skills/payments/stripe-spend, so wrapping that logic in
the package (Day 4-5) doesn't require translating between two shapes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Band(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


@dataclass
class AuthorityState:
    """Mirrors the shape of state/authority.json exactly."""
    band: Band
    per_action_cap: float
    session_cap: float
    spent_this_session: float = 0.0

    def remaining_session_budget(self) -> float:
        return self.session_cap - self.spent_this_session

    @classmethod
    def from_dict(cls, d: dict) -> "AuthorityState":
        return cls(
            band=Band(d["band"]),
            per_action_cap=float(d["per_action_cap"]),
            session_cap=float(d["session_cap"]),
            spent_this_session=float(d.get("spent_this_session", 0.0)),
        )

    def to_dict(self) -> dict:
        return {
            "band": self.band.value,
            "per_action_cap": self.per_action_cap,
            "session_cap": self.session_cap,
            "spent_this_session": self.spent_this_session,
        }


@dataclass
class SpendRequest:
    """A request to spend real money, before any policy decision is made."""
    amount: float
    description: str
    recipe: Optional[str] = None
    to: Optional[str] = None
    message: Optional[str] = None
    requested_at: float = field(default_factory=time.time)


class Verdict(str, Enum):
    AUTONOMOUS = "autonomous"      # within band, execute now, no human involved
    ESCALATION_REQUIRED = "escalation_required"  # over cap, human approval needed
    DENIED = "denied"               # explicitly denied by a human


@dataclass
class Decision:
    """The policy engine's verdict on a SpendRequest, given an AuthorityState."""
    verdict: Verdict
    request: SpendRequest
    reason: str
    band: Band


@dataclass
class PendingApproval:
    """Mirrors state/pending_approval.json exactly. The approval code itself
    is never part of this record — it exists only on Twilio's servers and the
    operator's phone."""
    amount: float
    description: str
    reason: str
    created_at: float = field(default_factory=time.time)

    def is_expired(self, ttl_seconds: int = 600) -> bool:
        return (time.time() - self.created_at) > ttl_seconds

    @classmethod
    def from_dict(cls, d: dict) -> "PendingApproval":
        return cls(
            amount=float(d["amount"]),
            description=d["description"],
            reason=d.get("reason", ""),
            created_at=float(d.get("created_at", time.time())),
        )

    def to_dict(self) -> dict:
        return {
            "amount": self.amount,
            "description": self.description,
            "reason": self.reason,
            "created_at": self.created_at,
        }


@dataclass
class KillSwitchState:
    """The kill switch: when engaged, the engine refuses every request
    regardless of band or amount, no exceptions. This is an operator-only
    control -- engaging/disengaging it is not exposed to the agent itself,
    only to a human via the CLI."""
    killed: bool = False
    reason: str = ""
    by: str = ""
    changed_at: float = field(default_factory=time.time)

    @classmethod
    def from_dict(cls, d: dict) -> "KillSwitchState":
        return cls(
            killed=bool(d.get("killed", False)),
            reason=d.get("reason", ""),
            by=d.get("by", ""),
            changed_at=float(d.get("changed_at", time.time())),
        )

    def to_dict(self) -> dict:
        return {
            "killed": self.killed,
            "reason": self.reason,
            "by": self.by,
            "changed_at": self.changed_at,
        }


@dataclass
class AuditEntry:
    """Mirrors the fields already written by _core.append_log()."""
    event: str
    amount: float
    description: str
    band: Band
    ts: float = field(default_factory=time.time)
    approved_by: Optional[str] = None
    denied_by: Optional[str] = None
    payment_intent_id: Optional[str] = None
    stripe_status: Optional[str] = None
    reason: Optional[str] = None
    error: Optional[str] = None
    recipe: Optional[str] = None
    recipe_result: Optional[str] = None
    recipe_error: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "event": self.event,
            "amount": self.amount,
            "description": self.description,
            "band": self.band.value if isinstance(self.band, Band) else self.band,
            "ts": self.ts,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.ts)),
        }
        for k in (
            "approved_by", "denied_by", "payment_intent_id", "stripe_status",
            "reason", "error", "recipe", "recipe_result", "recipe_error",
        ):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AuditEntry":
        return cls(
            event=d["event"],
            amount=float(d.get("amount", 0.0)),
            description=d.get("description", ""),
            band=d.get("band", "L2"),
            ts=float(d.get("ts", time.time())),
            approved_by=d.get("approved_by"),
            denied_by=d.get("denied_by"),
            payment_intent_id=d.get("payment_intent_id"),
            stripe_status=d.get("stripe_status"),
            reason=d.get("reason"),
            error=d.get("error"),
            recipe=d.get("recipe"),
            recipe_result=d.get("recipe_result"),
            recipe_error=d.get("recipe_error"),
        )
