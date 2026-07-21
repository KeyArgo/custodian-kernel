"""Dependency-free stdio MCP server for Custodian Codex Guard."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .approvals import ApprovalError, ApprovalStore, action_digest
from .guard import ActionKind, evaluate_action
from .receipts import ReceiptChain
from custodian.control.policy import ApprovalPolicy, Proposal
from custodian.control.filesystem_policy import FilesystemPolicy


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
            "required": ["tool", "action_kind", "arguments", "workspace", "requester"],
            "properties": {
                "tool": {"type": "string", "minLength": 1},
                "action_kind": {"type": "string", "enum": [k.value for k in ActionKind]},
                "arguments": {"type": "object"},
                "workspace": {"type": "string", "minLength": 1},
                "intent": {"type": "string"},
                "session_id": {"type": "string"},
                "requester": {"type": "string", "minLength": 1},
                "policy_version": {"type": "string"},
                "approval_id": {"type": "string"},
            },
        },
    },
    {
        "name": "verify_receipts",
        "description": "Verify the HMAC hash chain for all local Codex Guard receipts.",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
]


def evaluate_guard_action(args: dict[str, Any], *, harness: str = "codex") -> dict[str, Any]:
    """Evaluate one exact proposal for any supported harness.

    Harness identity is supplied by the trusted adapter, never by model tool
    arguments. Operator policy is applied to every action, including otherwise
    autonomous reads/writes, so an explicit deny/ask rule cannot be skipped.
    """
    if not harness or len(harness) > 64:
        raise ValueError("invalid harness identity")
    chain = ReceiptChain(_state_dir())
    try:
        model = os.environ.get("CUSTODIAN_TRUSTED_MODEL_ID", "*")
        requested_kind = str(args.get("action_kind", ""))
        access = "read" if requested_kind == "read" else "write"
        fs_config = FilesystemPolicy(_state_dir() / "filesystem-policy.json").fence_config(
            harness=harness, model=model, access=access,
            inherited_allow=[args.get("workspace", "")],
            inherited_deny=["~/.ssh", "~/.aws", "~/.config/gcloud", "~/.kube"],
        )
        decision = evaluate_action(
            tool=args.get("tool", ""), action_kind=requested_kind,
            arguments=args.get("arguments"), workspace=args.get("workspace", ""),
            intent=args.get("intent", ""), forbidden_paths=fs_config["forbidden_paths"],
            allow_paths=fs_config["allow_paths"],
        ).to_dict()
        decision["filesystem_policy"] = {
            "harness": harness, "model": model, "source": fs_config["source"],
            "enforcement": fs_config["enforcement"],
        }
        requester = args["requester"]
        proposal = Proposal(
            adapter=harness, action_kind=decision["action_kind"],
            tool=args["tool"], requester=requester, workspace=args["workspace"],
        )
        mode, rule_id = ApprovalPolicy(_state_dir() / "approval-policy.json").decide(proposal)

        # Mandatory adapter denials always win. Explicit operator denial is
        # next. A matching `ask` rule can promote an autonomous action.
        if decision["verdict"] != "denied" and mode == "deny":
            decision.update(verdict="denied", reason="blocked by operator policy",
                            policy_rule_id=rule_id)
        elif decision["verdict"] == "autonomous" and mode == "ask" and rule_id:
            decision.update(verdict="escalation_required",
                            reason="matching operator policy requires approval",
                            policy_rule_id=rule_id, band="L3")

        if decision["verdict"] == "escalation_required":
            digest = action_digest(
                tool=args["tool"], action_kind=decision["action_kind"],
                arguments=args["arguments"], workspace=args["workspace"],
                requester=requester, policy_version=args.get("policy_version", "default"),
            )
            store = ApprovalStore(_state_dir())
            approval_id = args.get("approval_id")
            if approval_id:
                store.consume(approval_id, digest=digest, requester=requester)
                decision.update(verdict="approved",
                                reason="exact action approved once by the human operator",
                                approval_id=approval_id)
            elif mode == "auto":
                exact = store.request(digest=digest, requester=requester)
                store.approve(exact.approval_id, approved_by=f"policy:{rule_id}",
                              expected_digest=digest)
                store.consume(exact.approval_id, digest=digest, requester=requester)
                decision.update(verdict="approved",
                                reason="exact action approved by scoped operator policy",
                                approval_id=exact.approval_id, policy_rule_id=rule_id)
            else:
                pending = store.request(digest=digest, requester=requester)
                decision.update(
                    approval_id=pending.approval_id, action_digest=digest,
                    approval_expires_at=pending.expires_at,
                    next_step=("Open `custodian console`, or ask the operator to run: "
                               f"custodian-codex approve {pending.approval_id} --digest {digest}"),
                )
        receipt = chain.append(decision, tool=args.get("tool", ""),
                               session_id=args.get("session_id", "default"))
        decision["receipt"] = {"timestamp": receipt["ts"], "chain_mac": receipt["mac"]}
        return decision
    except ApprovalError as exc:
        denied = {"verdict": "denied", "reason": str(exc),
                  "action_kind": str(args.get("action_kind", "unknown")),
                  "band": "L4", "enforcement_required": True}
        receipt = chain.append(denied, tool=args.get("tool", ""),
                               session_id=args.get("session_id", "default"))
        denied["receipt"] = {"timestamp": receipt["ts"], "chain_mac": receipt["mac"]}
        return denied
    except Exception as exc:
        return {"verdict": "denied",
                "reason": f"guard evaluation failed closed ({type(exc).__name__})",
                "enforcement_required": True}


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
            decision = evaluate_guard_action(args, harness="codex")
            return _text_result(decision, is_error=decision.get("verdict") == "denied")
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
