"""Map a Hermes tool call onto the shared Custodian guard decision.

The heavy lifting -- path fencing, secret/prompt-injection scanning, operator
policy, expiring single-use approvals, and value-free HMAC-chained receipts --
lives in :func:`custodian.guards.codex.mcp_server.evaluate_guard_action`,
exactly the same core the Codex, Claude, and OpenCode guards call. This
module only translates Hermes' tool vocabulary into an action kind and shapes
the request; it never decides policy on its own.
"""

from __future__ import annotations

from typing import Any

from custodian.guards.codex.mcp_server import evaluate_guard_action

from .contract import HERMES_GUARD_CONTRACT_VERSION, classify_tool


def evaluate_tool(payload: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one Hermes tool call and return a guard decision.

    Missing or malformed fields fail closed. ``approval_id`` is optional and
    is only useful for an exact retry after a scoped operator policy has
    minted one (or an operator approved the pending digest out-of-band).

    The returned dict uses the shared engine's schema (``verdict`` in
    {autonomous, approved, escalation_required, denied}, plus
    ``approval_id``/``action_digest``/``approval_expires_at``/``receipt``
    when applicable). Callers must treat ``escalation_required`` as *not*
    permission to execute.
    """
    if not isinstance(payload, dict):
        return {"verdict": "denied", "reason": "invalid Hermes tool proposal"}
    tool = payload.get("tool")
    arguments = payload.get("arguments")
    workspace = payload.get("workspace")
    requester = payload.get("requester")
    if not isinstance(tool, str) or not tool or not isinstance(arguments, dict):
        return {"verdict": "denied", "reason": "incomplete Hermes tool proposal"}
    if (not isinstance(workspace, str) or not workspace
            or not isinstance(requester, str) or not requester):
        return {"verdict": "denied",
                "reason": "Hermes identity and workspace are required"}

    request = {
        "tool": tool,
        "action_kind": classify_tool(tool),
        "arguments": arguments,
        "workspace": workspace,
        "intent": str(payload.get("intent", "Hermes tool execution"))[:512],
        "requester": requester,
        "session_id": str(payload.get("session_id", requester))[:128],
        "policy_version": HERMES_GUARD_CONTRACT_VERSION,
    }
    approval_id = payload.get("approval_id")
    if isinstance(approval_id, str) and approval_id:
        request["approval_id"] = approval_id
    try:
        decision = evaluate_guard_action(request, harness="hermes")
    except Exception as exc:  # pragma: no cover - exact exception is irrelevant
        return {"verdict": "denied", "reason": f"Custodian unavailable ({type(exc).__name__})"}
    if not isinstance(decision, dict) or decision.get("verdict") not in {
        "autonomous", "approved", "escalation_required", "denied",
    }:
        return {"verdict": "denied", "reason": "invalid Custodian response"}
    return decision
