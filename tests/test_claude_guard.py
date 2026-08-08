"""Tests for the Claude Code guard: classification, the PreToolUse hook
decision mapping, fail-closed behavior, and installer merge safety.

The through-line: unlike Codex's opt-in ``guard_action`` MCP tool, this guard
runs in Claude Code's ``PreToolUse`` hook, so its single most important property
is that *every* abnormal path resolves to an explicit deny -- never to a silent
exit-0-with-no-JSON, which Claude Code would treat as "no decision" and allow.
"""
import json

import pytest

from custodian.claude_guard.bridge import classify_tool, evaluate_tool
from custodian.claude_guard import cli, hook
from custodian.codex_guard.guard import _inferred_kind, ActionKind


@pytest.mark.parametrize(("tool", "kind"), [
    ("Read", "read"), ("Glob", "read"), ("Grep", "read"), ("TodoWrite", "read"),
    ("Edit", "write"), ("Write", "write"), ("MultiEdit", "write"),
    ("NotebookEdit", "write"),
    ("Bash", "test"),
    ("WebFetch", "network"), ("WebSearch", "network"),
    ("Task", "governance"), ("SlashCommand", "governance"),
    # Every unknown/MCP tool must escalate, never be assumed a read.
    ("mcp__stripe__create_charge", "governance"),
    ("SomeFutureTool", "governance"),
])
def test_classification(tool, kind):
    assert classify_tool(tool) == kind


def event(tmp_path, **overrides):
    value = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(tmp_path / "x.py")},
        "cwd": str(tmp_path),
        "session_id": "sess-1",
    }
    value.update(overrides)
    return value


def _state(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(state))
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state))
    # The claude guard's hook refuses to act when the gate is off; every
    # test in this file that exercises the hook (decide is fine without
    # it) must have the guard active.
    from custodian.guards.gate import enable as _gate_enable
    _gate_enable(str(state), "claude")


def test_read_allows(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    decision, _ = hook.decide(event(tmp_path))
    assert decision == "allow"


def test_workspace_write_allows(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    decision, _ = hook.decide(event(
        tmp_path, tool_name="Write",
        tool_input={"file_path": str(tmp_path / "b.py"), "content": "x"}))
    assert decision == "allow"


def test_network_escalates_to_ask(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    decision, reason = hook.decide(event(
        tmp_path, tool_name="WebFetch", tool_input={"url": "http://example"}))
    assert decision == "ask"
    assert "approval" in reason.lower()


def test_forbidden_path_denies(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    decision, _ = hook.decide(event(
        tmp_path, tool_name="Write",
        tool_input={"file_path": "~/.ssh/authorized_keys", "content": "k"}))
    assert decision == "deny"


def test_unknown_mcp_tool_escalates(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    decision, _ = hook.decide(event(
        tmp_path, tool_name="mcp__stripe__create_charge",
        tool_input={"amount": 9999}))
    assert decision == "ask"


def test_ask_reason_has_no_codex_next_step(tmp_path, monkeypatch):
    """The native ask dialog is the approval; the Codex out-of-band
    'custodian-codex approve ...' instruction must not leak into Claude's UI."""
    _state(monkeypatch, tmp_path)
    _, reason = hook.decide(event(
        tmp_path, tool_name="WebFetch", tool_input={"url": "http://x"}))
    assert "custodian-codex approve" not in reason


# --- fail-closed matrix ----------------------------------------------------

@pytest.mark.parametrize("bad_event", [
    {},                                   # empty
    {"tool_name": ""},                    # blank tool
    {"tool_name": 123},                   # non-string tool
    "not-a-dict",                         # wrong type entirely
    {"tool_name": "Read", "tool_input": {"file_path": "x"}, "cwd": ""},  # no workspace
])
def test_malformed_events_fail_closed(bad_event, tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    decision, _ = hook.decide(bad_event)
    assert decision == "deny"


@pytest.mark.parametrize("bad_session_id", [None, "", 42, []])
def test_missing_session_id_fails_closed(bad_session_id, tmp_path, monkeypatch):
    """A previous version fell back to the literal "unknown" for a missing
    session_id, which let two unrelated sessions that both omitted it share
    one requester identity and cross-consume each other's digest-bound
    approvals. session_id is a standard, always-present field in Claude
    Code's real PreToolUse payload, so treat a missing one as the same kind
    of anomaly as a missing tool name: fail closed, not shared."""
    _state(monkeypatch, tmp_path)
    decision, reason = hook.decide(event(tmp_path, session_id=bad_session_id))
    assert decision == "deny"
    assert "session_id" in reason


def test_home_workspace_fails_closed(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    decision, _ = hook.decide(event(tmp_path, cwd=str(pytest.importorskip("pathlib").Path.home())))
    assert decision == "deny"


def test_hook_main_emits_deny_on_garbage_stdin(tmp_path, monkeypatch, capsys):
    _state(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin("not json"))
    rc = hook.main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_main_echoes_session_start_event(tmp_path, monkeypatch, capsys):
    """Regression: the SessionStart hook shares this entrypoint with
    PreToolUse but Claude Code validates that the response's hookEventName
    matches the incoming event — the old hardcoded PreToolUse echo made
    Claude fail to start with 'expected SessionStart but got PreToolUse'."""
    _state(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin(
        '{"hook_event_name": "SessionStart", "cwd": "/tmp"}'
    ))
    rc = hook.main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "permissionDecision" not in out["hookSpecificOutput"]


def test_hook_main_echoes_input_event_name(tmp_path, monkeypatch, capsys):
    """The response event name must follow the input for PreToolUse too."""
    _state(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin(
        '{"hook_event_name": "PreToolUse", "tool_name": "Read", '
        '"tool_input": {"file_path": "/tmp/x"}, "session_id": "s1", "cwd": "/tmp"}'
    ))
    rc = hook.main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"


def test_bridge_rejects_incomplete_payload():
    assert evaluate_tool({"tool": "Read"})["verdict"] == "denied"
    assert evaluate_tool("nope")["verdict"] == "denied"


class _FakeStdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


# --- regression: the newline-separator destructive bypass we fixed ---------

@pytest.mark.parametrize("command", [
    "echo hi\nrm -rf ~/project",
    "cat <<EOF\nfoo\nEOF\nshred -u ~/.aws/credentials",
    "echo done\ngit reset --hard HEAD~3",
])
def test_newline_separated_destructive_is_caught(command):
    """A destructive command on any line after the first -- separated only by a
    newline, not ;/&/| -- was classified as a harmless local action and ran
    autonomously. Confirmed and fixed in codex_guard/guard.py."""
    assert _inferred_kind("Bash", {"command": command}) == ActionKind.DESTRUCTIVE


def test_benign_multiline_command_not_flagged():
    assert _inferred_kind("Bash", {"command": "echo a\necho b\nls -la"}) is None


# --- installer merge safety ------------------------------------------------

def test_setup_merges_without_clobbering(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "model": "opus",
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-hook"}]},
        ]},
    }))
    rc = cli.main(["setup", "--settings", str(settings)])
    assert rc == 0
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"                       # untouched
    commands = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert "other-hook" in commands                      # pre-existing hook kept
    assert any("custodian.claude_guard.hook" in c for c in commands)


def test_setup_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    cli.main(["setup", "--settings", str(settings)])
    cli.main(["setup", "--settings", str(settings)])
    data = json.loads(settings.read_text())
    ours = [e for e in data["hooks"]["PreToolUse"]
            if any("custodian.claude_guard.hook" in h.get("command", "")
                   for h in e.get("hooks", []))]
    assert len(ours) == 1                                # not duplicated


def test_setup_refuses_invalid_settings_file(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{ this is not json")
    with pytest.raises(SystemExit):
        cli.main(["setup", "--settings", str(settings)])
    assert settings.read_text() == "{ this is not json"  # left untouched


def test_uninstall_removes_only_ours(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-hook"}]},
        ]},
    }))
    cli.main(["setup", "--settings", str(settings)])
    cli.main(["uninstall", "--settings", str(settings)])
    data = json.loads(settings.read_text())
    commands = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
    assert commands == ["other-hook"]
