"""Policy schema: dataclasses for the policy specification.

Deliberately not a full expression language — match conditions are a fixed,
small vocabulary (skill name, context flags, a spend-amount threshold).
That's enough to express real authority policies and simple enough to
implement and test correctly in the time available; a general-purpose
condition grammar is exactly the kind of "looks sophisticated, isn't tested"
trap a 9-day build can't afford.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from custodian.exceptions import PolicyValidationError
from custodian.types import Band

# Only backends with a real, shipped implementation belong here. A policy
# citing a backend name that isn't actually wired would otherwise pass
# validation and only fail silently at escalation time -- that's a false
# claim of capability, not a real feature. Add a name here only in the same
# change that ships its ApprovalBackend implementation.
VALID_APPROVAL_BACKENDS = {"twilio_verify", "none"}


@dataclass
class BandConfig:
    name: Band
    max_spend: Optional[float]  # None means unbounded for this band (still may require approval)
    requires_approval: bool
    approval_backend: Optional[str] = None
    description: str = ""

    def validate(self) -> None:
        if self.max_spend is not None and self.max_spend < 0:
            raise PolicyValidationError(
                f"band {self.name}: max_spend must be >= 0, got {self.max_spend}"
            )
        if self.requires_approval and not self.approval_backend:
            raise PolicyValidationError(
                f"band {self.name}: requires_approval=true but no approval_backend set"
            )
        if self.approval_backend and self.approval_backend not in VALID_APPROVAL_BACKENDS:
            raise PolicyValidationError(
                f"band {self.name}: unknown approval_backend '{self.approval_backend}' "
                f"(valid: {sorted(VALID_APPROVAL_BACKENDS)})"
            )


@dataclass
class MatchCondition:
    """A fixed, small vocabulary of things a rule can match on."""
    skill: Optional[str] = None
    context_flag: Optional[str] = None    # e.g. "critical" -- matches context["critical"] truthy
    context_flag_equals: Optional[bool] = None  # paired with context_flag, default True
    spend_estimate_gt: Optional[float] = None

    def matches(self, skill: Optional[str], context: dict, spend_estimate: Optional[float]) -> bool:
        if self.skill is not None and self.skill != skill:
            return False
        if self.context_flag is not None:
            expected = True if self.context_flag_equals is None else self.context_flag_equals
            if bool(context.get(self.context_flag)) != expected:
                return False
        if self.spend_estimate_gt is not None:
            if spend_estimate is None or not (spend_estimate > self.spend_estimate_gt):
                return False
        return True


@dataclass
class Rule:
    match: MatchCondition
    assign_band: Band
    order: int = 0  # rules are evaluated in (order, declaration index) order; first match wins


@dataclass
class EscalationConfig:
    timeout_seconds: int = 600
    on_timeout: str = "deny"  # "deny" is the only safe default; "retry" requires explicit opt-in
    retry_count: int = 0

    def validate(self) -> None:
        if self.timeout_seconds <= 0:
            raise PolicyValidationError("escalation.timeout_seconds must be positive")
        if self.on_timeout not in ("deny", "retry"):
            raise PolicyValidationError(
                f"escalation.on_timeout must be 'deny' or 'retry', got '{self.on_timeout}'"
            )
        if self.retry_count < 0:
            raise PolicyValidationError("escalation.retry_count must be >= 0")


@dataclass
class Policy:
    version: str
    default_band: Band
    bands: dict[Band, BandConfig]
    rules: list[Rule] = field(default_factory=list)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)

    def validate(self) -> None:
        if self.version != "1.0":
            raise PolicyValidationError(f"unsupported policy version: {self.version}")
        if self.default_band not in self.bands:
            raise PolicyValidationError(
                f"default_band '{self.default_band}' is not defined in bands: "
                f"{sorted(b.value for b in self.bands)}"
            )
        for band_cfg in self.bands.values():
            band_cfg.validate()
        for rule in self.rules:
            if rule.assign_band not in self.bands:
                raise PolicyValidationError(
                    f"rule assigns undefined band '{rule.assign_band}'"
                )
        self.escalation.validate()

    def band_for(self, skill: Optional[str], context: dict, spend_estimate: Optional[float]) -> Band:
        """First matching rule wins, in declared order; falls back to default_band."""
        ordered = sorted(self.rules, key=lambda r: r.order)
        for rule in ordered:
            if rule.match.matches(skill, context, spend_estimate):
                return rule.assign_band
        return self.default_band
