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
    # "apply_patch" is the actual tool name OpenAI's real Codex CLI uses for
    # file edits -- it was missing from this set entirely, so a proposal
    # naming it this way never triggered the sensitive-config-write check
    # below despite being a normal, expected way to reach it.
    "apply_patch": ActionKind.WRITE,
    "update_file": ActionKind.WRITE,
    "write": ActionKind.WRITE,
    "file-delete": ActionKind.DESTRUCTIVE,
    "delete_file": ActionKind.DESTRUCTIVE,
    "git-push": ActionKind.NETWORK,
    "deploy": ActionKind.PRODUCTION,
    "remove-item": ActionKind.DESTRUCTIVE,
    "invoke-webrequest": ActionKind.NETWORK,
    "invoke-restmethod": ActionKind.NETWORK,
}
_SHELL_RULES = (
    (re.compile(
        r"\bcustodian-codex\s+(?:approve|disable|setup)\b"
        r"|\bcustodian\.codex_guard\.cli\s+(?:approve|disable|setup)\b"
        r"|\bopencode\b|\bcustodian-opencode\s+(?:setup|evaluate)\b", re.I,
    ), ActionKind.GOVERNANCE),
    (re.compile(
        r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:rm|rmdir|shred|truncate|del|erase|rd)\b"
        r"|\b(?:remove-item|clear-content|format-volume)\b"
        r"|\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f)", re.I,
    ), ActionKind.DESTRUCTIVE),
    (re.compile(
        r"\b(?:kubectl|helm|terraform)\s+(?:apply|destroy|upgrade|install)\b"
        r"|\b(?:gcloud\s+run|az\s+deployment|aws\s+cloudformation)\b"
        r"|\bdocker\s+push\b|\b(?:deploy|release)\b", re.I,
    ), ActionKind.PRODUCTION),
    (re.compile(
        r"\bgit\s+push\b|\b(?:curl|wget|ssh|scp|rsync)\b"
        r"|\b(?:invoke-webrequest|invoke-restmethod)\b|(?:^|\s)(?:iwr|irm)\s", re.I,
    ), ActionKind.NETWORK),
    (re.compile(r"\b(?:paladin|vault)\b|paladin://|warden://", re.I), ActionKind.CREDENTIAL),
)

_SENSITIVE_WRITE_PATH = re.compile(
    r"(?:^|[\\/])(?:\.github[\\/]workflows|\.gitlab-ci\.yml|Dockerfile|"
    r"docker-compose(?:\.[^\\/]+)?\.ya?ml|pyproject\.toml|package\.json|"
    r"requirements(?:\.[^\\/]+)?\.txt|\.codex|\.agents)(?:$|[\\/])",
    re.I,
)


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _strings(nested)


def _inferred_kind(tool: str, arguments: dict[str, Any]) -> ActionKind | None:
    normalized = tool.strip().lower()
    mapped = None
    if normalized in _TOOL_KINDS:
        mapped = _TOOL_KINDS[normalized]
        if mapped in _ESCALATE:
            return mapped
    if normalized in {"shell", "bash", "terminal", "shell-exec", "exec", "exec_command"}:
        raw_command = arguments.get("command", arguments.get("cmd", ""))
        # An argv-list command (e.g. ["git","push","--force","origin","main"])
        # must not be str()'d directly -- that produces its Python repr
        # ("['git', 'push', ...]"), whose stray quotes/brackets/commas break
        # every _SHELL_RULES pattern that requires whitespace between words
        # or an anchor, silently defeating risk inference for exactly the
        # tool-call shape a real coding agent uses.
        if isinstance(raw_command, (list, tuple)):
            command = " ".join(str(part) for part in raw_command)
        else:
            command = str(raw_command)
        for pattern, inferred in _SHELL_RULES:
            if pattern.search(command):
                return inferred
    surfaces = tuple(_strings(arguments))
    if any("paladin://" in value or "warden://" in value for value in surfaces):
        return ActionKind.CREDENTIAL
    # Keyed off the same _TOOL_KINDS mapping (rather than a second,
    # independently-maintained literal tool-name set) so a write-shaped tool
    # name missing from this check can't silently reappear the way
    # "apply_patch" -- the real Codex CLI's actual edit tool name -- did.
    if mapped == ActionKind.WRITE:
        if any(_SENSITIVE_WRITE_PATH.search(value) for value in surfaces):
            return ActionKind.GOVERNANCE
    return mapped


def _is_unreasonable_workspace_root(resolved: Path) -> bool:
    """A legitimate project workspace is a specific subdirectory -- never the
    caller's entire home directory or a filesystem root. Since `workspace`
    is a value the model itself declares (see mcp_server.py's own docstring:
    harness identity is pinned by the trusted adapter, but workspace is not),
    accepting either of these would let virtually any real-world path
    ("~/.bashrc", "/etc/passwd") resolve as "inside the workspace,"
    defeating the entire containment boundary with an ordinary-looking
    value an agent could plausibly declare on its own.
    """
    if resolved == Path.home().resolve():
        return True
    if resolved.parent == resolved:  # filesystem root ("/", "C:\\", ...)
        return True
    return False


def _pipeline(workspace: str, forbidden_paths: list[str] | None,
              allow_paths: list[str] | None = None) -> AdapterPipeline:
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
            "allow_paths": allow_paths if allow_paths is not None else [root],
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
    allow_paths: list[str] | None = None,
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

    try:
        resolved_workspace = Path(workspace).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        resolved_workspace = None
    if resolved_workspace is None or _is_unreasonable_workspace_root(resolved_workspace):
        return GuardDecision(
            verdict="denied",
            action_kind=kind.value,
            reason=("declared workspace is the home directory, a filesystem root, or "
                    "unresolvable; a real project workspace must be a specific "
                    "subdirectory -- Custodian fails closed"),
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
    result = _pipeline(workspace, forbidden_paths, allow_paths).run_pre(ctx)
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
