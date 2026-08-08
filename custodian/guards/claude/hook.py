"""Claude Code ``PreToolUse`` hook entrypoint for Custodian Guard.

Claude Code invokes this on stdin before every governed tool call and reads a
JSON decision back on stdout. This is the enforcement boundary, so it is written
to fail closed under every failure mode:

* A malformed request, an unclassifiable tool, an unavailable control plane, or
  any unexpected exception all resolve to an explicit ``deny`` -- never to
  silence. That matters because Claude Code treats *exit 0 with no parseable
  JSON* as "no decision" and falls back to its normal permission flow, so a
  guard that merely crashed would fail **open**. We therefore always print a
  decision, and only ever exit non-zero (code 2, a hard block) if we somehow
  cannot even serialize one.

Verdict mapping:

* ``denied``               -> ``deny``  (tool call is blocked outright)
* ``escalation_required``  -> ``ask``   (Claude Code's native permission dialog
                                          becomes the human approval step)
* ``autonomous``/``approved`` -> ``allow``
* anything unexpected      -> ``deny``  (fail closed)
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .bridge import evaluate_tool

_HANDLED = {"autonomous", "approved", "escalation_required", "denied"}


def _emit(decision: str, reason: str = "", event_name: str = "PreToolUse") -> None:
    """Write one hook decision and flush. Never raises to the caller.

    Claude Code validates that the response's ``hookEventName`` matches the
    incoming event's ``hook_event_name``; echoing it is required for the
    SessionStart hook (which shares this entrypoint with PreToolUse).
    """
    output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": decision,
        }
    }
    if reason:
        output["hookSpecificOutput"]["permissionDecisionReason"] = reason[:1024]
    sys.stdout.write(json.dumps(output))
    sys.stdout.flush()


def decide(event: dict[str, Any]) -> tuple[str, str]:
    """Map a Claude Code PreToolUse event to a (permissionDecision, reason).

    Pure and side-effect-light (the receipt/ledger write happens inside the
    shared core) so it can be unit-tested without touching stdio.
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
        # session_id is a standard, always-present field in Claude Code's
        # PreToolUse hook payload, not an optional one. A previous version
        # substituted the literal "unknown" here, which collapsed every event
        # missing this field onto the SAME requester identity
        # ("claude:unknown") -- letting one malformed-event session's
        # digest-bound approval be auto-consumed by an unrelated one that also
        # happened to omit session_id. Fail closed instead, matching every
        # other required-field check in this function, rather than silently
        # sharing an identity across sessions that were never actually the
        # same requester.
        return "deny", "Custodian: missing session_id; failing closed"
    session_id = session_id_raw[:128]
    # cwd is supplied by the trusted harness, not by the model, so it is a
    # sound workspace root. Running Claude Code from a bare home directory or a
    # filesystem root is rejected upstream by the shared core by design -- run
    # it from the project subdirectory instead.
    workspace = str(event.get("cwd") or "")

    payload = {
        "tool": tool,
        "arguments": tool_input,
        "workspace": workspace,
        "requester": f"claude:{session_id}",
        "session_id": session_id,
        "intent": f"Claude Code {tool} call",
    }
    decision = evaluate_tool(payload)
    verdict = decision.get("verdict") if isinstance(decision, dict) else None
    reason = str(decision.get("reason", "")) if isinstance(decision, dict) else ""
    # Note: we deliberately do NOT surface the shared core's `next_step`
    # ("run custodian-codex approve ID --digest ..."). That out-of-band
    # approval dance is Codex's model; in Claude Code the native `ask`
    # permission dialog this returns *is* the human approval step.

    if verdict == "denied":
        return "deny", f"Custodian denied this action: {reason}" if reason else "Custodian denied this action"
    if verdict == "escalation_required":
        return "ask", f"Custodian requires approval: {reason}" if reason else "Custodian requires approval"
    if verdict in ("autonomous", "approved"):
        from custodian.guards.codex.mcp_server import _state_dir
        from custodian.control.settings import ControlSettingsStore
        if ControlSettingsStore(
            _state_dir() / "control-settings.json"
        ).load().visibility == "quiet":
            reason = ""
        return "allow", reason
    # Unknown / missing verdict: fail closed.
    return "deny", "Custodian: unrecognized guard verdict; failing closed"


def _dormant_defer(event_name: str = "PreToolUse") -> bool:
    """If the claude guard is disabled in the gate, emit defer and return True."""
    import os
    from pathlib import Path
    from custodian.guards.gate import is_enabled, is_fail_closed
    state_dir = os.environ.get("CUSTODIAN_STATE_DIR", str(Path.home() / ".custodian"))
    if is_fail_closed(state_dir):
        # Corrupt state with no valid backup: deny everything until the
        # operator repairs the gate state. Never silently disarm.
        _emit("deny", "Custodian gate state is unreadable — failing closed", event_name)
        return True
    if not is_enabled(state_dir, "claude"):
        _emit("defer", "Custodian claude guard is disabled in this profile", event_name)
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}
    event_name = event.get("hook_event_name")
    if not isinstance(event_name, str) or not event_name:
        event_name = "PreToolUse"
    if event_name == "SessionStart":
        # The SessionStart hook shares this entrypoint with PreToolUse but
        # has no tool decision to make: acknowledge with the matching event
        # name (no permissionDecision) so Claude Code accepts the hook.
        sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart"}}))
        sys.stdout.flush()
        return 0
    if _dormant_defer(event_name):
        return 0
    try:
        decision, reason = decide(event)
    except Exception as exc:  # fail closed on anything at all
        try:
            _emit("deny", f"Custodian hook failed closed ({type(exc).__name__})", event_name)
            return 0
        except Exception:
            # Could not even print a decision -- use the exit-2 hard block so
            # Claude Code still refuses the tool call instead of proceeding.
            sys.stderr.write("Custodian guard error; tool call blocked\n")
            return 2
    _emit(decision, reason, event_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
