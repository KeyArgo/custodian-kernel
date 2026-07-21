"""Stable shared control-plane contracts for Codex, Talaria/Hermes,
Paladin, and the delegated executor.

Every adapter and integration maps its own proposal shapes into these
neutral contracts.  The kernel never imports an integration package;
integrations import *this* module (or consume the documented JSON
shape).  This is the only file that defines the cross-component wire
format — change it only when the shared protocol changes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import time
from typing import Any, Optional
from uuid import uuid4

from custodian.types import sanitize_dict

# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

#: Hex string from ``uuid4().hex`` — the single correlation token traced
#: through every lifecycle transition across all components.
CorrelationId = str


def new_correlation_id() -> CorrelationId:
    return uuid4().hex


#: "Source" names the control plane recognises.  Integration packages
#: MAY register additional source strings via ``register_source()``;
#: the four defined here are guaranteed stable.
WELL_KNOWN_SOURCES = frozenset({
    "codex",
    "talaria",
    "hermes",
    "paladin",
    "executor",
    "kernel",
    "console",
    "operator",
})

# ---------------------------------------------------------------------------
# Enforcement level  (CONTROL_PLANE_TOPOLOGY.md "Enforcement strength")
# ---------------------------------------------------------------------------

class EnforcementLevel(str, Enum):
    """How strongly an adapter enforces the kernel's decision.

    Every adapter declares one of these; no UI or documentation may
    describe a weaker level as universal interception.
    """
    ADVISORY = "advisory"     # recommendation only
    ROUTED = "routed"         # cooperating caller consults Custodian
    BROKERED = "brokered"     # real capability lives behind executor
    NATIVE = "native"         # host lifecycle hook prevents bypass

    @classmethod
    def strictest(cls) -> EnforcementLevel:
        return cls.NATIVE

    def cannot_bypass(self) -> bool:
        return self in (EnforcementLevel.BROKERED, EnforcementLevel.NATIVE)


# ---------------------------------------------------------------------------
# Approval semantics  (mirrors policy.py MODES — deny/ask/auto)
# ---------------------------------------------------------------------------

class ApprovalSemantics(str, Enum):
    """How a proposal is resolved when no explicit override exists.

    Alignment: ``policy.py``'s ``MODES`` and ``codex_guard/``'s verdict
    strings map 1:1 into these three values.
    """
    DENY = "deny"       # rejected outright — operator must explicitly unblock
    ASK = "ask"         # human approval required before execution
    AUTO = "auto"       # may proceed autonomously within band

    def requires_human(self) -> bool:
        return self is ApprovalSemantics.ASK

    def is_governed(self) -> bool:
        """Return True if a human must be (or may be) involved."""
        return self is not ApprovalSemantics.DENY


# ---------------------------------------------------------------------------
# Lifecycle event
# ---------------------------------------------------------------------------

#: Normalised lifecycle transitions.  Every component emits events using
#: these strings so the universal ledger stores a single vocabulary.
LIFECYCLE_TRANSITIONS = frozenset({
    "proposed",             # action submitted to the authority boundary
    "evaluated",            # policy decision reached
    "allowed",              # approved to proceed (autonomous OR human-approved)
    "denied",               # rejected by policy or human
    "approval_requested",   # human approval has been asked for
    "approved",             # human approved
    "execution_started",    # capability consumed, execution begun
    "succeeded",            # execution completed successfully
    "failed",               # execution completed with error
    "reversed",             # action was rolled back (e.g. refund)
})


@dataclass(frozen=True)
class ControlEvent:
    """A normalised, sanitised lifecycle event for the universal ledger.

    Every field is safe for logging, audit, and model context — no
    secrets, prompts, file contents, or command arguments are present.
    Callers supply raw event data; the sanitizer strips secret-bearing
    keys (same pattern as ``custodian.types.sanitize_dict``) before the
    event is stored.

    All fields are immutable.  Use ``to_dict()`` for JSON serialization.
    """

    event_type: str
    correlation_id: CorrelationId
    source: str
    action_digest: str
    enforcement_level: EnforcementLevel
    approval_semantics: ApprovalSemantics
    timestamp: float = field(default_factory=time.time)
    event_data: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.event_type not in LIFECYCLE_TRANSITIONS:
            raise ValueError(
                f"unknown event_type {self.event_type!r}; "
                f"must be one of {sorted(LIFECYCLE_TRANSITIONS)}"
            )
        if self.source not in WELL_KNOWN_SOURCES:
            raise ValueError(
                f"unknown source {self.source!r}; "
                f"must be one of {sorted(WELL_KNOWN_SOURCES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.event_data) if self.event_data else {}
        return {
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "action_digest": self.action_digest,
            "enforcement_level": self.enforcement_level.value,
            "approval_semantics": self.approval_semantics.value,
            "timestamp": self.timestamp,
            "event_data": sanitize_dict(data) if data else {},
        }


# ---------------------------------------------------------------------------
# Sanitizer — strips secrets from event payloads
# ---------------------------------------------------------------------------

class ControlEventSanitizer:
    """Produces sanitized event data from a raw payload.

    Reuses ``custodian.types.sanitize_dict`` to strip secret-bearing
    keys.  This is stateless — kept as a class so callers can inject a
    custom sanitizer if needed.
    """

    SANITIZE_KEYS = frozenset({
        "command", "cmd", "args", "arguments", "prompt", "secret", "password",
        "token", "credential", "api_key", "authorization", "cookie",
    })

    @classmethod
    def sanitize(cls, raw: Optional[dict]) -> dict[str, Any]:
        if not raw:
            return {}
        return sanitize_dict(raw)

    @classmethod
    def sanitize_event_data(cls, raw: Optional[dict]) -> tuple[tuple[str, Any], ...]:
        cleaned = cls.sanitize(raw)
        return tuple(cleaned.items())


# ---------------------------------------------------------------------------
# Decision  (single gate shared by all adapters)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ControlDecision:
    """A normalised policy decision — the single gate that replaces every
    adapter-specific ``Verdict``, ``GuardDecision``, and ``Decision`` shape
    across Codex, Talaria/Hermes, Paladin, and the executor.

    Every integration translates its own verdict into this type; no
    integration's competing gate is exposed to the ledger or to consumers.
    """
    verdict: str                # "autonomous" | "escalation_required" | "denied"
    reason: str
    enforcement_level: EnforcementLevel
    approval_semantics: ApprovalSemantics
    correlation_id: CorrelationId = field(default_factory=new_correlation_id)
    action_digest: str = ""
    approved_by: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.verdict not in {"autonomous", "escalation_required", "denied"}:
            raise ValueError(f"unknown verdict {self.verdict!r}")

    @property
    def is_allowed(self) -> bool:
        return self.verdict == "autonomous"

    @property
    def is_denied(self) -> bool:
        return self.verdict == "denied"

    @property
    def is_escalated(self) -> bool:
        return self.verdict == "escalation_required"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "enforcement_level": self.enforcement_level.value,
            "approval_semantics": self.approval_semantics.value,
            "correlation_id": self.correlation_id,
            "action_digest": self.action_digest,
            "approved_by": self.approved_by,
            "timestamp": self.timestamp,
        }

    @classmethod
    def autonomous(
        cls, *, reason: str = "autonomous within authority band",
        enforcement_level: EnforcementLevel = EnforcementLevel.ROUTED,
        **kwargs: Any,
    ) -> ControlDecision:
        return cls(
            verdict="autonomous", reason=reason,
            enforcement_level=enforcement_level,
            approval_semantics=ApprovalSemantics.AUTO,
            **kwargs,
        )

    @classmethod
    def escalation(
        cls, *, reason: str = "human approval required",
        enforcement_level: EnforcementLevel = EnforcementLevel.ROUTED,
        **kwargs: Any,
    ) -> ControlDecision:
        return cls(
            verdict="escalation_required", reason=reason,
            enforcement_level=enforcement_level,
            approval_semantics=ApprovalSemantics.ASK,
            **kwargs,
        )

    @classmethod
    def denied(
        cls, *, reason: str = "denied by policy or enforcement",
        enforcement_level: EnforcementLevel = EnforcementLevel.ROUTED,
        **kwargs: Any,
    ) -> ControlDecision:
        return cls(
            verdict="denied", reason=reason,
            enforcement_level=enforcement_level,
            approval_semantics=ApprovalSemantics.DENY,
            **kwargs,
        )

    @classmethod
    def fail_closed(
        cls, *, reason: str = "fail closed: unexpected state",
        **kwargs: Any,
    ) -> ControlDecision:
        return cls.denied(
            reason=reason,
            enforcement_level=EnforcementLevel.NATIVE,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Enforcement report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnforcementReport:
    """Structured enforcement-level report that every adapter produces.

    ``enforced_as`` records the actual enforcement level that was
    applied (which may be stricter than the adapter's declared level if
    the kernel overrides it — e.g. an ``advisory`` adapter over a
    ``brokered`` capability must report ``brokered``).
    """
    adapter: str
    source: str
    correlation_id: CorrelationId
    action_digest: str
    declared_level: EnforcementLevel
    enforced_as: EnforcementLevel
    approved_semantics: ApprovalSemantics
    outcome: str               # "allowed" | "denied" | "escalated"
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["declared_level"] = self.declared_level.value
        data["enforced_as"] = self.enforced_as.value
        data["approved_semantics"] = self.approved_semantics.value
        return data

    @classmethod
    def from_decision(
        cls, *, adapter: str, source: str,
        decision: ControlDecision,
    ) -> EnforcementReport:
        outcome_map = {
            "autonomous": "allowed",
            "escalation_required": "escalated",
            "denied": "denied",
        }
        return cls(
            adapter=adapter,
            source=source,
            correlation_id=decision.correlation_id,
            action_digest=decision.action_digest,
            declared_level=decision.enforcement_level,
            enforced_as=decision.enforcement_level,
            approved_semantics=decision.approval_semantics,
            outcome=outcome_map.get(decision.verdict, "denied"),
            reason=decision.reason,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "ApprovalSemantics",
    "ControlDecision",
    "ControlEvent",
    "ControlEventSanitizer",
    "CorrelationId",
    "EnforcementLevel",
    "EnforcementReport",
    "LIFECYCLE_TRANSITIONS",
    "WELL_KNOWN_SOURCES",
    "new_correlation_id",
]
