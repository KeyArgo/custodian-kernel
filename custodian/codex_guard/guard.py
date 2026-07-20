"""Fail-closed policy bridge between coding-agent tools and Custodian guards.

This module never executes a proposed action.  It returns a decision that the
caller must enforce, keeping the policy boundary separate from the model and
from any particular website or IDE.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Any

from custodian.adapters import ActionContext, AdapterPipeline
from custodian.adapters.builtin import (
    KernelSelfProtection,
    PathFence,
    PromptInjectionGuard,
    SecretLeakGuard,
)


class ActionKind(str, Enum):
    READ = "read"
    TEST = "test"
    WRITE = "write"
    NETWORK = "network"
    CREDENTIAL = "credential"
    DESTRUCTIVE = "destructive"
    PRODUCTION = "production"
    MONEY = "money"
    GOVERNANCE = "governance"


@dataclass(frozen=True)
class GuardDecision:
    verdict: str
    action_kind: str
    reason: str
    band: str
    enforcement_required: bool = True
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["warnings"] = list(self.warnings)
        return result


_AUTONOMOUS = {ActionKind.READ, ActionKind.TEST, ActionKind.WRITE}
_ESCALATE = {
    ActionKind.NETWORK,
    ActionKind.CREDENTIAL,
    ActionKind.DESTRUCTIVE,
    ActionKind.PRODUCTION,
    ActionKind.MONEY,
    ActionKind.GOVERNANCE,
}

_TOOL_KINDS = {
    "write_file": ActionKind.WRITE,
    "file-write": ActionKind.WRITE,
    "patch": ActionKind.WRITE,
    "edit_file": ActionKind.WRITE,
    "file-delete": ActionKind.DESTRUCTIVE,
    "delete_file": ActionKind.DESTRUCTIVE,
    "git-push": ActionKind.NETWORK,
    "deploy": ActionKind.PRODUCTION,
}
_SHELL_RULES = (
    (re.compile(r"(?:^|[;&|]\s*)(?:rm|rmdir|shred|truncate)\b|git\s+(?:reset\s+--hard|clean\s+-f)", re.I), ActionKind.DESTRUCTIVE),
    (re.compile(r"\b(?:kubectl|helm|terraform)\s+(?:apply|destroy)|\b(?:deploy|release)\b", re.I), ActionKind.PRODUCTION),
    (re.compile(r"\bgit\s+push\b|\b(?:curl|wget|ssh|scp|rsync)\b", re.I), ActionKind.NETWORK),
    (re.compile(r"\b(?:paladin|vault)\b|paladin://|warden://", re.I), ActionKind.CREDENTIAL),
)


def _inferred_kind(tool: str, arguments: dict[str, Any]) -> ActionKind | None:
    normalized = tool.strip().lower()
    if normalized in _TOOL_KINDS:
        return _TOOL_KINDS[normalized]
    if normalized in {"shell", "bash", "terminal", "shell-exec", "exec_command"}:
        command = str(arguments.get("command", arguments.get("cmd", "")))
        for pattern, inferred in _SHELL_RULES:
            if pattern.search(command):
                return inferred
    return None


def _pipeline(workspace: str, forbidden_paths: list[str] | None) -> AdapterPipeline:
    root = str(Path(workspace).expanduser().resolve())
    forbidden = forbidden_paths or [
        "~/.ssh", "~/.aws", "~/.config/gcloud", "~/.kube",
    ]
    return AdapterPipeline([
        KernelSelfProtection(),
        # Scan values before path parsing so a credential embedded in a shell
        # argument is identified as a leak, not misreported as a path token.
        SecretLeakGuard(),
        PromptInjectionGuard({"strict": True}),
        PathFence({
            "forbidden_paths": forbidden,
            "forbidden_globs": ["*.env", "*.pem", "id_rsa", "id_ed25519"],
            "allow_paths": [root],
            "base_path": root,
        }),
    ])


def evaluate_action(
    *,
    tool: str,
    action_kind: str,
    arguments: dict[str, Any] | None,
    workspace: str,
    intent: str = "",
    forbidden_paths: list[str] | None = None,
) -> GuardDecision:
    """Evaluate one proposed action without executing it.

    Unknown action kinds fail closed. Adapter denials take precedence over
    authority bands. Consequential classes require a separate human approval;
    callers must not interpret escalation as permission to execute.
    """
    try:
        kind = ActionKind(action_kind)
    except (TypeError, ValueError):
        return GuardDecision(
            verdict="denied",
            action_kind=str(action_kind),
            reason="unknown action kind; Custodian fails closed",
            band="L4",
        )

    if not tool or not isinstance(arguments or {}, dict):
        return GuardDecision(
            verdict="denied",
            action_kind=kind.value,
            reason="tool and object-shaped arguments are required",
            band="L4",
        )

    inferred = _inferred_kind(tool, arguments or {})
    # A caller may overstate risk, never understate it. This prevents a model
    # from labeling `rm`, `git push`, or deployment as a harmless local read.
    effective_kind = inferred if inferred in _ESCALATE else kind

    ctx = ActionContext(
        skill=tool,
        args=arguments or {},
        description=intent,
        band="L1" if effective_kind in _AUTONOMOUS else "L3",
    )
    result = _pipeline(workspace, forbidden_paths).run_pre(ctx)
    warnings = tuple(v.reason for v in result.warnings if v.reason)
    if not result.allowed:
        reasons = "; ".join(v.reason for v in result.denials if v.reason)
        return GuardDecision(
            verdict="denied",
            action_kind=effective_kind.value,
            reason=reasons or "a mandatory security guard denied the action",
            band="L4",
            warnings=warnings,
        )
    if effective_kind in _ESCALATE:
        classification_note = (
            f"; independently classified from the proposed tool (caller supplied {kind.value})"
            if inferred is not None and inferred != kind else ""
        )
        return GuardDecision(
            verdict="escalation_required",
            action_kind=effective_kind.value,
            reason=(f"{effective_kind.value} actions require explicit human approval"
                    f"{classification_note}"),
            band="L3",
            warnings=warnings,
        )
    return GuardDecision(
        verdict="autonomous",
        action_kind=kind.value,
        reason=f"{kind.value} action is within the workspace safety boundary",
        band="L1",
        warnings=warnings,
    )
