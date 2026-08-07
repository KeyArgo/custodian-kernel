"""Public, versioned contract for the Custodian Hermes integration.

This module is the single source of truth for the wire contract between a
Hermes Agent process and Custodian:

* the normalized tool-event payload (:class:`HermesToolEvent`);
* the decision schema returned to the plugin (:class:`HermesDecision`);
* the Hermes tool vocabulary -> action-kind classification
  (:func:`classify_tool`);
* the verdict -> Hermes hook directive mapping (:func:`verdict_to_directive`).

Versioning: bump :data:`HERMES_GUARD_CONTRACT_VERSION` on any breaking change
to the payload, decision schema, classification, or directive mapping. The
repository-owned plugin and the runtime must agree on this version; a
mismatch is a deployment error and must fail closed, never silently proceed.

Classification policy (matches the Claude/OpenCode bridges):

* Unknown tools -- including every future Hermes built-in -- classify as
  ``governance`` so they escalate for human review the first time rather
  than executing on an optimistic guess. The operator can lower a specific
  trusted tool to autonomous via an approval-policy rule; the guard never
  silently widens.
* ``terminal``/``process``/``execute_code`` classify as ``test``: the shared
  decision engine independently promotes network, destructive, production,
  credential, and governance-shaped commands by inspecting the actual
  command string, and fences protected paths referenced inside it.
* The shared engine's path fence denies writes to operator-protected
  locations regardless of which tool carries the path, so a shell redirect
  is treated exactly like a ``write_file`` targeting the same file.

Decision semantics (mirrors the shared engine):

* ``autonomous``      -- allowed, no approval.
* ``approved``        -- allowed, exact action was approved once.
* ``escalation_required`` -- NOT permission. Requires operator approval
                            bound to the exact action digest; expires.
* ``denied``          -- blocked, never executes.

Receipts: every decision is appended to the tamper-evident receipt chain
with harness identity ``hermes``. Receipts are value-free and are never
surfaced to the model by this adapter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

#: Breaking changes to the payload/decision schema, classification, or
#: directive mapping must bump this and ship the plugin/runtime together.
HERMES_GUARD_CONTRACT_VERSION = "1.0"


def approval_wait_seconds(raw=None) -> int:
    """Resolve the approval-wait window from the environment.

    Order of precedence: explicit ``raw`` argument (for tests) > the
    brand-neutral ``CUSTODIAN_APPROVAL_WAIT_SECONDS`` > the legacy
    ``TALARIA_APPROVAL_WAIT_SECONDS`` (kept as a compatibility shim for
    operators who haven't migrated their environment yet) > 300.

    The window is clamped to the same ``[_MIN_WAIT_SECONDS,
    _MAX_WAIT_SECONDS]`` bounds as the runtime, so a typo'd "0" or "9999"
    never pins or skips a session.
    """
    from .runtime import _MAX_WAIT_SECONDS, _MIN_WAIT_SECONDS  # late import: no cycle

    if raw is None:
        raw = os.environ.get(
            "CUSTODIAN_APPROVAL_WAIT_SECONDS",
            os.environ.get("TALARIA_APPROVAL_WAIT_SECONDS", "300"),
        )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 300.0
    return int(max(_MIN_WAIT_SECONDS, min(_MAX_WAIT_SECONDS, value)))

#: Verdicts the shared engine may return. Anything else is a guard failure
#: and must be treated as a denial (fail closed).
KNOWN_VERDICTS = frozenset({"autonomous", "approved", "escalation_required", "denied"})

# ---------------------------------------------------------------------------
# Hermes tool vocabulary -> action kind
# ---------------------------------------------------------------------------

# Local, read-only inspection: no external side effect, no state change.
# `todo` mutates an ephemeral in-session list and `clarify` prompts the
# human operator; neither reaches an external system, matching how the
# Claude bridge treats TodoWrite.
_READ_TOOLS = frozenset({
    "read_file", "search_files", "session_search",
    "skills_list", "skill_view",
    "todo", "clarify",
    "turbofit_status",
})
# Ordinary workspace edits (the shared core's PathFence confines these to
# the allowed workspace root and denies protected paths).
_WRITE_TOOLS = frozenset({"write_file", "patch"})
# Shell/code execution. The shared engine inspects the actual command
# string and independently promotes risky commands out of the autonomous
# band, exactly like Claude's "Bash" -> test classification.
_TEST_TOOLS = frozenset({"terminal", "process", "execute_code"})
# Anything that reaches the network or an external service/model.
_NETWORK_TOOLS = frozenset({
    "browser_navigate", "browser_back", "browser_click", "browser_press",
    "browser_scroll", "browser_snapshot", "browser_console",
    "browser_get_images", "browser_type", "browser_vision",
    "web_extract", "web_search",
    "image_generate", "video_generate", "video_analyze",
    "vision_analyze", "text_to_speech",
})
# Delegated / arbitrary-capability / persistent-state tools -- treated as
# governance so an unreviewed one escalates rather than running on an
# assumption. A model delegating work (delegate_task), driving the desktop
# (computer_use), editing skills or persistent memory (skill_manage,
# memory), scheduling jobs (cronjob), or changing provider configuration
# (turbofit_configure) must not run without operator review.
_GOVERNANCE_TOOLS = frozenset({
    "memory", "skill_manage", "cronjob", "delegate_task",
    "computer_use", "turbofit_configure",
})


def classify_tool(tool: str) -> str:
    """Return the action kind for a Hermes tool name.

    Unknown tools deliberately fall through to ``governance`` so they
    escalate for human review the first time rather than executing on an
    optimistic guess (identical policy to the Claude and OpenCode bridges).
    """
    normalized = str(tool).strip().lower()
    if normalized in _READ_TOOLS:
        return "read"
    if normalized in _WRITE_TOOLS:
        return "write"
    if normalized in _TEST_TOOLS:
        return "test"
    if normalized in _NETWORK_TOOLS:
        return "network"
    if normalized in _GOVERNANCE_TOOLS:
        return "governance"
    return "governance"


# ---------------------------------------------------------------------------
# Payload / decision schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HermesToolEvent:
    """Normalized, canonical description of one proposed Hermes tool call.

    Every field is supplied by the trusted adapter/plugin layer, never by
    model tool arguments. ``workspace`` must be a specific project
    subdirectory -- never the home directory or a filesystem root, which
    the shared engine rejects.
    """

    tool: str
    arguments: dict[str, Any]
    workspace: str
    requester: str
    session_id: str = ""
    task_id: str = ""
    intent: str = ""
    approval_id: str = ""
    correlation_id: str = ""


@dataclass(frozen=True)
class HermesDecision:
    """Decision for one Hermes tool call, as seen by the plugin.

    ``allowed`` is the only field the plugin may act on: True means the
    call may proceed, False means it must be blocked. ``escalation_required``
    is *not* permission -- the plugin must obtain the exact approval bound
    to ``action_digest`` (see :meth:`HermesGuardRuntime.wait_for_approval`)
    before executing, and the approval expires.
    """

    verdict: str
    allowed: bool
    action_kind: str
    reason: str = ""
    notification: str = ""
    approval_id: str = ""
    action_digest: str = ""
    approval_expires_at: Optional[float] = None
    policy_rule_id: str = ""
    receipt: Optional[dict[str, Any]] = None

    @classmethod
    def from_engine(cls, decision: dict[str, Any], *, notification: str = "") -> "HermesDecision":
        """Wrap a shared-engine decision dict into the contract schema.

        Any unknown/missing verdict fails closed: the call is not allowed.
        """
        verdict = str(decision.get("verdict", "")) if isinstance(decision, dict) else ""
        allowed = verdict in {"autonomous", "approved"}
        return cls(
            verdict=verdict,
            allowed=allowed,
            action_kind=str(decision.get("action_kind", "unknown")),
            reason=str(decision.get("reason", "")),
            notification=notification or str(decision.get("reason", "")),
            approval_id=str(decision.get("approval_id", "") or ""),
            action_digest=str(decision.get("action_digest", "") or ""),
            approval_expires_at=decision.get("approval_expires_at"),
            policy_rule_id=str(decision.get("policy_rule_id", "") or ""),
            receipt=decision.get("receipt"),
        )


# ---------------------------------------------------------------------------
# Verdict -> Hermes hook directive
# ---------------------------------------------------------------------------


def verdict_to_directive(
    decision: HermesDecision,
    *,
    quiet: bool = False,
) -> Optional[dict[str, str]]:
    """Map a decision to the Hermes ``pre_tool_call`` return contract.

    Returns ``None`` when the tool call may proceed (Hermes runs it), or
    ``{"action": "block", "message": <reason>}`` when it must be blocked
    (Hermes turns the message into the tool result the model sees).

    ``quiet`` suppresses the model-facing explanation for allowed decisions
    only; a block always carries a reason because Hermes requires one.
    """
    if decision.allowed:
        if quiet:
            return None
        # Allowed actions still carry no directive -- Hermes proceeds
        # silently; explanatory prose for an ordinary passing gate is noise.
        return None
    message = decision.notification or f"Custodian blocked this {decision.action_kind}: {decision.reason}"
    if decision.approval_id:
        message += f" Approval: {decision.approval_id}"
    return {"action": "block", "message": f"[hermes-guard] {message}"}
