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


# -- Optional opt-in directives -------------------------------------------------
#
# The original Custodian policy only had three things to enforce: per-band
# max_spend, session cap, and self-approval detection. We are adding four
# OPT-IN directives (daily envelope, margin gate, auto-downgrade, and
# self-dealing detection). They are deliberately wired in as Optional
# fields with sensible None/false defaults so existing policies — and the
# dozens of existing tests that pin their behavior — continue to work
# unchanged. The new checks only fire when the corresponding directive
# is set, and the evaluator's try/except wrapper around each check means
# a malformed directive logs and continues rather than blowing up the
# decision.
#
# Adding an Optional field with a default of None is not a public-API
# change to Policy / BandConfig: existing constructors that pass the
# previous set of arguments still work, load_policy() still loads the
# same YAML shape, and Policy.validate() still passes on every policy
# that does not opt into the new directives.

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

    # --- Opt-in policy directives (all default to None / disabled) ------------
    # Each is read by its dedicated check in custodian.policy.{envelope,autorank}.
    # None / unset means "do not run this check for this band" — preserves
    # 100% backward compatibility with policies that don't know about them.
    daily_envelope: Optional[float] = None
    band_after_task: Optional[Band] = None

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
        if self.daily_envelope is not None and self.daily_envelope < 0:
            raise PolicyValidationError(
                f"band {self.name}: daily_envelope must be >= 0, got {self.daily_envelope}"
            )


@dataclass
class MarginsConfig:
    """Optional margin-gate directives (opt-in at the Policy level).

    A policy that doesn't set `margins:` simply has no margin gate enforced.
    This is what makes the new directive truly opt-in: no existing test
    that constructs a Policy() without a margins field ever sees the
    check_margin() path run.
    """
    minimum_margin: Optional[float] = None
    minimum_margin_pct: Optional[float] = None

    def validate(self) -> None:
        if self.minimum_margin is not None and self.minimum_margin < 0:
            raise PolicyValidationError(
                f"margins.minimum_margin must be >= 0, got {self.minimum_margin}"
            )
        if self.minimum_margin_pct is not None and (
            self.minimum_margin_pct < 0 or self.minimum_margin_pct > 100
        ):
            raise PolicyValidationError(
                f"margins.minimum_margin_pct must be in [0, 100], "
                f"got {self.minimum_margin_pct}"
            )


@dataclass
class PoliciesConfig:
    """Top-level `policies:` block — a place for opt-in policy toggles that
    don't fit cleanly inside a single band (i.e. they're request-level
    checks, not per-band caps)."""
    no_self_dealing: bool = False


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
    # Opt-in policy-level directives. The defaults preserve full backward
    # compatibility: a Policy() constructed without these never invokes the
    # new checks. `margins=None` is the sentinel that check_margin() looks
    # for; same for `policies=None` in check_self_dealing().
    margins: Optional[MarginsConfig] = None
    policies: Optional[PoliciesConfig] = None

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
        if self.margins is not None:
            self.margins.validate()
        # If a band declares band_after_task, it must be a defined band —
        # otherwise a downgrade could route to a band that doesn't exist,
        # which would be a silent fail-open in the wrong direction.
        for band_cfg in self.bands.values():
            if band_cfg.band_after_task is not None and band_cfg.band_after_task not in self.bands:
                raise PolicyValidationError(
                    f"band {band_cfg.name.value}: band_after_task "
                    f"'{band_cfg.band_after_task.value}' is not defined in bands"
                )

    def band_for(self, skill: Optional[str], context: dict, spend_estimate: Optional[float]) -> Band:
        """First matching rule wins, in declared order; falls back to default_band."""
        ordered = sorted(self.rules, key=lambda r: r.order)
        for rule in ordered:
            if rule.match.matches(skill, context, spend_estimate):
                return rule.assign_band
        return self.default_band
