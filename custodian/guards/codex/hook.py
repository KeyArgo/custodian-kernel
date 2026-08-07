"""Codex CLI ``PreToolUse`` hook entrypoint for Custodian Guard.

This is the enforcement upgrade over the opt-in ``guard_action`` MCP tool: Codex
invokes this on stdin before every governed tool call and blocks the call if we
say so. Enforcement no longer depends on the model *choosing* to consult the
guard, on the ``govern-codex`` skill being loaded, or on a prompt surviving
injection. Because a PreToolUse deny is evaluated before Codex's own approval
decision, it blocks even under ``approval_policy = "never"`` or a
``trust_level = "trusted"`` project -- that is the "100% through the kernel"
guarantee -- but only once this hook is itself Trusted or Managed. A plain
user-level install starts Untrusted and is silently skipped in non-interactive
``codex exec`` until approved once in the TUI; see ``custodian-codex setup``'s
own output and ``docs/ROADMAP-codex-kernel-enforcement.md`` for the live
smoke-test finding this qualifier comes from.

Codex's PreToolUse contract is deliberately narrow (verified against the
codex-cli 0.144.6 binary): a hook may only **deny** (``permissionDecision:
"deny"`` with a *required*, non-empty reason) or **defer** (emit nothing, so
Codex's normal approval flow proceeds). It cannot force-allow or ask -- the
runtime rejects ``permissionDecision:allow`` and ``:ask``. So this guard can
only ever *restrict*, never widen, which is exactly what we want. Verdict map:

* ``denied``               -> deny
* ``escalation_required``  -> deny, with the single-use ``custodian-codex
                              approve ID --digest DIGEST`` instructions in the
                              reason (Codex has no native "ask"; the existing
                              out-of-band approval flow is the ask, and the
                              identical approved re-run resolves to ``approved``)
* ``autonomous``/``approved`` -> defer (no output)
* anything unexpected      -> deny (fail closed)

Fail-closed is the single most important property: a crash that exited 0 with no
JSON would be read by Codex as "no decision" and fall through to normal flow, so
every abnormal path here emits an explicit deny (or, if it cannot even print
one, exits 2 -- which Codex also treats as a hard block).
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .mcp_server import evaluate_guard_action

# Codex tool-name -> base action kind. The shared core independently promotes
# destructive/network/production/credential/governance-shaped *shell commands*
# out of the autonomous band by inspecting the command string, so `shell` only
# needs a conservative base of "test" here.
_READ_TOOLS = frozenset({
    "read_file", "read", "cat", "list_dir", "ls", "glob", "grep",
    "view_image", "update_plan", "todo",
})
_WRITE_TOOLS = frozenset({"apply_patch", "write_file", "edit_file", "update_file", "patch"})
_NETWORK_TOOLS = frozenset({"web_search", "web.run", "browser"})
_SHELL_TOOLS = frozenset({
    "shell", "bash", "exec", "exec_command", "local_shell", "terminal",
    "container.exec",
})


def classify_tool(tool: str) -> str:
    normalized = str(tool).strip().lower()
    if normalized in _READ_TOOLS:
        return "read"
    if normalized in _WRITE_TOOLS:
        return "write"
    if normalized in _NETWORK_TOOLS:
        return "network"
    if normalized in _SHELL_TOOLS:
        return "test"
    # Every unknown/MCP (`mcp__*`) tool escalates rather than being assumed safe.
    return "governance"


def _emit_deny(reason: str) -> None:
    # Codex REQUIRES a non-empty permissionDecisionReason with a deny, so never
    # let the reason collapse to empty.
    reason = (reason or "Custodian denied this action").strip() or "Custodian denied this action"
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason[:1024],
        }
    }))
    sys.stdout.flush()


def _emit_defer() -> None:
    # Emit nothing: Codex reads "no decision" and applies its normal approval
    # flow. We never force-allow (the runtime rejects permissionDecision:allow).
    pass


def decide(event: dict[str, Any]) -> tuple[str, str]:
    """Map a Codex PreToolUse event to a ('deny'|'defer', reason).

    Kept pure (the receipt/ledger write happens inside the shared core) so it is
    unit-testable without touching stdio.
    """
    if not isinstance(event, dict):
        return "deny", "Custodian: malformed hook event; failing closed"
    tool = event.get("tool_name")
    tool_input = event.get("tool_input")
    if not isinstance(tool, str) or not tool:
        return "deny", "Custodian: missing tool name; failing closed"
    if not isinstance(tool_input, dict):
        tool_input = {}
    session_id_raw = event.get("session_id")
    if not isinstance(session_id_raw, str) or not session_id_raw:
        # session_id is a documented field in the real Codex PreToolUse event
        # (verified against the codex-cli 0.144.6 binary -- see
        # docs/ROADMAP-codex-kernel-enforcement.md), not an optional one. A
        # previous version substituted the literal "unknown" here, which
        # collapsed every event missing this field onto the SAME requester
        # identity ("codex:unknown") -- letting one malformed-event session's
        # digest-bound approval be auto-consumed by an unrelated one that also
        # happened to omit session_id. Fail closed instead, matching every
        # other required-field check in this function, rather than silently
        # sharing an identity across sessions that were never actually the
        # same requester.
        return "deny", "Custodian: missing session_id; failing closed"
    session_id = session_id_raw[:128]
    # cwd is supplied by the trusted harness, not the model. Running Codex from a
    # bare home directory or filesystem root is rejected upstream by the shared
    # core by design -- run it from the project subdirectory instead.
    workspace = str(event.get("cwd") or "")

    request = {
        "tool": tool,
        "action_kind": classify_tool(tool),
        "arguments": tool_input,
        "workspace": workspace,
        "requester": f"codex:{session_id}",
        "session_id": session_id,
        "intent": f"Codex {tool} call",
    }
    decision = evaluate_guard_action(request, harness="codex")
    verdict = decision.get("verdict") if isinstance(decision, dict) else None
    reason = str(decision.get("reason", "")) if isinstance(decision, dict) else ""

    if verdict in ("autonomous", "approved"):
        return "defer", ""
    if verdict == "escalation_required":
        # Codex has no native ask, so carry the out-of-band single-use approval
        # instructions in the (required) deny reason. Once the operator approves,
        # the identical re-run resolves to `approved` via the digest lookup.
        next_step = decision.get("next_step") if isinstance(decision, dict) else None
        msg = f"Custodian requires approval: {reason}" if reason else "Custodian requires approval"
        if next_step:
            msg = f"{msg}\n{next_step}"
        return "deny", msg
    if verdict == "denied":
        return "deny", f"Custodian denied this action: {reason}" if reason else "Custodian denied this action"
    # Unknown / missing verdict: fail closed.
    return "deny", "Custodian: unrecognized guard verdict; failing closed"


def main(argv: list[str] | None = None) -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        action, reason = decide(event)
    except Exception as exc:  # fail closed on anything at all
        try:
            _emit_deny(f"Custodian hook failed closed ({type(exc).__name__})")
            return 0
        except Exception:
            sys.stderr.write("Custodian guard error; tool call blocked\n")
            return 2
    if action == "deny":
        _emit_deny(reason)
    else:
        _emit_defer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
