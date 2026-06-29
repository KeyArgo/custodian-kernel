"""Load and validate a policy from YAML.

Errors here are deliberately specific (PolicyValidationError with a message
naming the exact field) -- a developer authoring a policy file should never
have to guess what's wrong from a generic parse traceback.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from custodian.exceptions import PolicyNotFoundError, PolicyValidationError
from custodian.policy.schema import (
    BandConfig,
    EscalationConfig,
    MatchCondition,
    Policy,
    Rule,
)
from custodian.types import Band


def _parse_band(raw: dict, name: str) -> BandConfig:
    try:
        band = Band(name)
    except ValueError:
        raise PolicyValidationError(
            f"unknown band name '{name}' (valid: {[b.value for b in Band]})"
        )
    return BandConfig(
        name=band,
        max_spend=raw.get("max_spend"),
        requires_approval=bool(raw.get("requires_approval", False)),
        approval_backend=raw.get("approval_backend"),
        description=raw.get("description", ""),
    )


def _parse_rule(raw: dict, order: int) -> Rule:
    match_raw = raw.get("match", {})
    if not isinstance(match_raw, dict):
        raise PolicyValidationError(f"rule {order}: 'match' must be a mapping")

    context_flag = None
    context_flag_equals = None
    for key, value in match_raw.items():
        if key.startswith("context."):
            context_flag = key.split(".", 1)[1]
            context_flag_equals = bool(value)

    match = MatchCondition(
        skill=match_raw.get("skill"),
        context_flag=context_flag,
        context_flag_equals=context_flag_equals,
        spend_estimate_gt=match_raw.get("spend_estimate_gt"),
    )

    assign_band_raw = raw.get("assign_band")
    if not assign_band_raw:
        raise PolicyValidationError(f"rule {order}: missing 'assign_band'")
    try:
        assign_band = Band(assign_band_raw)
    except ValueError:
        raise PolicyValidationError(
            f"rule {order}: unknown assign_band '{assign_band_raw}'"
        )

    return Rule(match=match, assign_band=assign_band, order=order)


def parse_policy(raw: dict) -> Policy:
    if "version" not in raw:
        raise PolicyValidationError("policy is missing required field 'version'")
    if "bands" not in raw or not isinstance(raw["bands"], dict):
        raise PolicyValidationError("policy is missing required field 'bands' (mapping)")
    if "default_band" not in raw:
        raise PolicyValidationError("policy is missing required field 'default_band'")

    bands = {}
    for name, band_raw in raw["bands"].items():
        cfg = _parse_band(band_raw or {}, name)
        bands[cfg.name] = cfg

    rules = [
        _parse_rule(rule_raw, i)
        for i, rule_raw in enumerate(raw.get("rules", []))
    ]

    esc_raw = raw.get("escalation", {})
    escalation = EscalationConfig(
        timeout_seconds=int(esc_raw.get("timeout_seconds", 600)),
        on_timeout=esc_raw.get("on_timeout", "deny"),
        retry_count=int(esc_raw.get("retry_count", 0)),
    )

    try:
        default_band = Band(raw["default_band"])
    except ValueError:
        raise PolicyValidationError(
            f"unknown default_band '{raw['default_band']}'"
        )

    policy = Policy(
        version=str(raw["version"]),
        default_band=default_band,
        bands=bands,
        rules=rules,
        escalation=escalation,
    )
    policy.validate()
    return policy


def load_policy(path: Path) -> Policy:
    if not path.exists():
        raise PolicyNotFoundError(f"no policy file found at {path}")
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise PolicyValidationError(f"failed to parse YAML in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise PolicyValidationError(f"policy file {path} did not parse to a mapping")
    return parse_policy(raw)
