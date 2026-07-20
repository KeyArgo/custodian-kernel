"""Dependency-free stdio MCP server for Custodian Codex Guard."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .guard import ActionKind, evaluate_action
from .receipts import ReceiptChain


def _state_dir() -> Path:
    configured = os.environ.get("CUSTODIAN_CODEX_GUARD_STATE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".custodian"


def _text_result(value: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
        "structuredContent": value,
        "isError": is_error,
    }


TOOLS = [
    {
        "name": "guard_action",
        "description": (
            "Evaluate a proposed Codex action before execution. A result of "
            "escalation_required is not permission; obtain human approval first."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["tool", "action_kind", "arguments", "workspace"],
            "properties": {
                "tool": {"type": "string", "minLength": 1},
                "action_kind": {"type": "string", "enum": [k.value for k in ActionKind]},
                "arguments": {"type": "object"},
                "workspace": {"type": "string", "minLength": 1},
                "intent": {"type": "string"},
                "session_id": {"type": "string"},
            },
        },
    },
    {
        "name": "verify_receipts",
        "description": "Verify the HMAC hash chain for all local Codex Guard receipts.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
]


def handle(method: str, params: dict[str, Any]) -> dict[str, Any] | None:
    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "custodian-codex-guard", "version": "0.1.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        chain = ReceiptChain(_state_dir())
        if name == "guard_action":
            try:
                decision = evaluate_action(
                    tool=args.get("tool", ""),
                    action_kind=args.get("action_kind", ""),
                    arguments=args.get("arguments"),
                    workspace=args.get("workspace", ""),
                    intent=args.get("intent", ""),
                ).to_dict()
                receipt = chain.append(
                    decision,
                    tool=args.get("tool", ""),
                    session_id=args.get("session_id", "default"),
                )
                decision["receipt"] = {
                    "timestamp": receipt["ts"],
                    "chain_mac": receipt["mac"],
                }
                return _text_result(decision)
            except Exception as exc:
                # Tool errors fail closed and avoid returning argument values.
                return _text_result({
                    "verdict": "denied",
                    "reason": f"guard evaluation failed closed ({type(exc).__name__})",
                    "enforcement_required": True,
                }, is_error=True)
        if name == "verify_receipts":
            try:
                count = chain.verify()
                return _text_result({"valid": True, "receipts": count})
            except Exception as exc:
                return _text_result({"valid": False, "reason": str(exc)}, is_error=True)
        return _text_result({"error": f"unknown tool: {name}"}, is_error=True)
    if method.startswith("notifications/"):
        return None
    raise ValueError(f"method not found: {method}")


def main() -> int:
    for raw in sys.stdin:
        request: Any = None
        try:
            request = json.loads(raw)
            request_id = request.get("id")
            result = handle(request.get("method", ""), request.get("params") or {})
            if request_id is None or result is None:
                continue
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if isinstance(request, dict) else None,
                "error": {"code": -32603, "message": str(exc)},
            }
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
