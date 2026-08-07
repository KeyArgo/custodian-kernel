"""Map a Claude Code tool call onto the shared Custodian guard decision.

The heavy lifting -- path fencing, secret/prompt-injection scanning, operator
policy, expiring single-use approvals, and value-free HMAC-chained receipts --
lives in :func:`custodian.guards.codex.mcp_server.evaluate_guard_action`, exactly
the same core the Codex and OpenCode guards call. This module only translates
Claude Code's tool vocabulary into an action kind and shapes the request; it
never decides policy on its own.
"""
from __future__ import annotations

from typing import Any

from custodian.guards.codex.mcp_server import evaluate_guard_action


# Local, read-only inspection: no external side effect, no state change.
_READ_TOOLS = frozenset({
    "read", "glob", "grep", "ls", "notebookread",
    "todowrite", "todoread", "bashoutput", "exitplanmode", "skill",
})
# Ordinary workspace edits (the PathFence in the shared core is what actually
# confines these to the allowed workspace root).
_WRITE_TOOLS = frozenset({"edit", "write", "multiedit", "notebookedit"})
# Anything that reaches the network.
_NETWORK_TOOLS = frozenset({"webfetch", "websearch"})
# Delegated / arbitrary-capability tools -- treated as governance so an
# unreviewed one escalates rather than running as an assumed read.
_GOVERNANCE_TOOLS = frozenset({"task", "slashcommand", "killshell"})


def classify_tool(tool: str) -> str:
    """Return the action kind for a Claude Code tool name.

    Unknown tools -- including every ``mcp__*`` connector tool -- deliberately
    fall through to ``governance`` so they escalate for human review the first
    time rather than executing on an optimistic guess. The operator can lower a
    specific trusted tool to autonomous via an approval-policy rule; the guard
    never silently widens.
    """
    normalized = str(tool).strip().lower()
    if normalized in _READ_TOOLS:
        return "read"
    if normalized in _WRITE_TOOLS:
        return "write"
    if normalized in _NETWORK_TOOLS:
        return "network"
    if normalized == "bash":
        # The shared guard independently promotes network, destructive,
        # production, credential, and governance-shaped commands out of the
        # autonomous band by inspecting the actual command string.
        return "test"
    if normalized in _GOVERNANCE_TOOLS:
        return "governance"
    # New built-in tools and every MCP tool must be classified deliberately
    # before they can run autonomously.
    return "governance"


def evaluate_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one Claude Code tool call and return a guard decision.

    Missing or malformed fields fail closed. ``approval_id`` is optional and is
    only useful for an exact retry after a scoped operator policy has minted one.
    """
    if not isinstance(payload, dict):
        return {"verdict": "denied", "reason": "invalid Claude Code proposal"}
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    workspace = payload.get("workspace")
    requester = payload.get("requester")
    if not isinstance(tool, str) or not tool or not isinstance(arguments, dict):
        return {"verdict": "denied", "reason": "incomplete Claude Code proposal"}
    if (not isinstance(workspace, str) or not workspace
            or not isinstance(requester, str) or not requester):
        return {"verdict": "denied",
                "reason": "Claude Code identity and workspace are required"}

    request = {
        "tool": tool,
        "action_kind": classify_tool(tool),
        "arguments": arguments,
        "workspace": workspace,
        "intent": str(payload.get("intent", "Claude Code tool execution"))[:512],
        "requester": requester,
        "session_id": str(payload.get("session_id", requester))[:128],
    }
    approval_id = payload.get("approval_id")
    if isinstance(approval_id, str) and approval_id:
        request["approval_id"] = approval_id
    try:
        decision = evaluate_guard_action(request, harness="claude")
    except Exception as exc:  # pragma: no cover - exact exception is irrelevant
        return {"verdict": "denied", "reason": f"Custodian unavailable ({type(exc).__name__})"}
    if not isinstance(decision, dict) or decision.get("verdict") not in {
        "autonomous", "approved", "escalation_required", "denied",
    }:
        return {"verdict": "denied", "reason": "invalid Custodian response"}
    return decision
