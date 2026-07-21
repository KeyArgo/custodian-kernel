"""JSON bridge used by the OpenCode ``tool.execute.before`` plugin.

The JavaScript hook is intentionally tiny.  Policy, approval storage, path
fencing, and receipt generation remain in Python so OpenCode and Codex use the
same enforcement implementation.
"""
from __future__ import annotations

from typing import Any

from custodian.codex_guard.mcp_server import evaluate_guard_action


_READ_TOOLS = frozenset({"read", "glob", "grep", "list", "lsp", "skill"})
_WRITE_TOOLS = frozenset({"edit", "write", "apply_patch"})
_NETWORK_TOOLS = frozenset({"webfetch", "websearch"})
_LOCAL_TOOLS = frozenset({"question", "todowrite", "todoread"})


def classify_tool(tool: str) -> str:
    normalized = str(tool).strip().lower()
    if normalized in _READ_TOOLS:
        return "read"
    if normalized in _WRITE_TOOLS:
        return "write"
    if normalized in _NETWORK_TOOLS:
        return "network"
    if normalized == "bash":
        # The shared guard independently promotes network, destructive,
        # production, credential, and governance-shaped commands.
        return "test"
    if normalized in _LOCAL_TOOLS:
        return "read"
    if normalized == "task":
        # A delegated agent can invoke any other tool.  Never assume that a
        # task is merely a read based on its natural-language prompt.
        return "governance"
    # New OpenCode tools must be classified deliberately before use.
    return "governance"


def evaluate_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one OpenCode tool call and return a Guard decision.

    Missing fields and malformed responses fail closed.  ``approval_id`` is
    optional and is only useful for an exact retry after operator approval.
    """
    if not isinstance(payload, dict):
        return {"verdict": "denied", "reason": "invalid OpenCode proposal"}
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    workspace = payload.get("workspace")
    requester = payload.get("requester")
    if not isinstance(tool, str) or not tool or not isinstance(arguments, dict):
        return {"verdict": "denied", "reason": "incomplete OpenCode proposal"}
    if not isinstance(workspace, str) or not workspace or not isinstance(requester, str) or not requester:
        return {"verdict": "denied", "reason": "OpenCode identity and workspace are required"}

    request = {
        "tool": tool,
        "action_kind": classify_tool(tool),
        "arguments": arguments,
        "workspace": workspace,
        "intent": str(payload.get("intent", "OpenCode tool execution"))[:512],
        "requester": requester,
        "session_id": str(payload.get("session_id", requester))[:128],
    }
    approval_id = payload.get("approval_id")
    if isinstance(approval_id, str) and approval_id:
        request["approval_id"] = approval_id
    try:
        decision = evaluate_guard_action(request, harness="opencode")
    except Exception as exc:  # pragma: no cover - exact exception is irrelevant
        return {"verdict": "denied", "reason": f"Custodian unavailable ({type(exc).__name__})"}
    if not isinstance(decision, dict) or decision.get("verdict") not in {
        "autonomous", "approved", "escalation_required", "denied",
    }:
        return {"verdict": "denied", "reason": "invalid Custodian response"}
    return decision
