import json
from pathlib import Path

import pytest

from custodian.opencode_guard.bridge import classify_tool, evaluate_tool
from custodian.opencode_guard import cli
from custodian.opencode_guard.plugin import plugin_source
from custodian.control.policy import ApprovalPolicy, ApprovalRule


@pytest.mark.parametrize(("tool", "kind"), [
    ("read", "read"), ("edit", "write"), ("write", "write"),
    ("apply_patch", "write"), ("bash", "test"),
    ("webfetch", "network"), ("websearch", "network"),
    ("task", "governance"), ("new-unknown-tool", "governance"),
])
def test_classification(tool, kind):
    assert classify_tool(tool) == kind


def proposal(tmp_path, **overrides):
    value = {
        "tool": "read", "arguments": {"filePath": str(tmp_path / "x")},
        "workspace": str(tmp_path), "requester": "opencode:test",
    }
    value.update(overrides)
    return value


def test_read_is_autonomous(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(tmp_path / "state"))
    assert evaluate_tool(proposal(tmp_path))["verdict"] == "autonomous"


def test_opencode_specific_write_deny_cannot_be_skipped(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(state))
    ApprovalPolicy(state / "approval-policy.json").add(
        ApprovalRule(mode="deny", adapter="opencode", action_kind="write")
    )
    result = evaluate_tool(proposal(
        tmp_path, tool="write",
        arguments={"filePath": str(tmp_path / "x"), "content": "ok"},
    ))
    assert result["verdict"] == "denied"
    assert result["reason"] == "blocked by operator policy"


def test_codex_rule_does_not_impersonate_opencode(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(state))
    ApprovalPolicy(state / "approval-policy.json").add(
        ApprovalRule(mode="deny", adapter="codex", action_kind="write")
    )
    result = evaluate_tool(proposal(
        tmp_path, tool="write", arguments={"filePath": str(tmp_path / "x")},
    ))
    assert result["verdict"] == "autonomous"


@pytest.mark.parametrize("tool", ["webfetch", "websearch", "task", "unknown"])
def test_consequential_or_unknown_escalates(tmp_path, monkeypatch, tool):
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(tmp_path / "state"))
    result = evaluate_tool(proposal(tmp_path, tool=tool, arguments={"url": "https://example.com"}))
    assert result["verdict"] == "escalation_required"
    assert result["approval_id"]


@pytest.mark.parametrize("command", [
    "git push origin main",
    "rm -rf ./build",
    "opencode run --auto fix this",
    "opencode --pure run change policy",
    "custodian-opencode setup",
])
def test_bash_cannot_hide_consequential_or_nested_harness(tmp_path, monkeypatch, command):
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(tmp_path / "state"))
    result = evaluate_tool(proposal(tmp_path, tool="bash", arguments={"command": command}))
    assert result["verdict"] == "escalation_required"


def test_invalid_payload_fails_closed():
    assert evaluate_tool({})["verdict"] == "denied"


def test_bridge_exception_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "custodian.opencode_guard.bridge.evaluate_guard_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()),
    )
    assert evaluate_tool(proposal(tmp_path))["verdict"] == "denied"


def test_plugin_guards_before_execution_and_rejects_bad_responses():
    source = plugin_source("/absolute/python")
    assert '"tool.execute.before"' in source
    assert "Bun.spawn" in source
    assert "malformed data" in source
    assert "validation failed" in source
    assert "/absolute/python" in source


def test_setup_doctor_and_tamper_detection(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/opencode")
    assert cli.main(["setup"]) == 0
    assert cli.main(["doctor"]) == 0
    path = tmp_path / "opencode" / "plugins" / "custodian-guard.js"
    path.write_text("tampered", encoding="utf-8")
    assert cli.main(["doctor"]) == 1


def test_launcher_rejects_pure_even_when_installed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/opencode")
    assert cli.main(["setup"]) == 0
    assert cli.main(["--pure"]) == 2
    assert "disables" in capsys.readouterr().err


@pytest.mark.parametrize("token", ["--pure=true", "--PURE", "--Pure:1"])
def test_launcher_rejects_pure_lookalikes(tmp_path, monkeypatch, capsys, token):
    """Regression: a plain `"--pure" in forwarded` exact-string check let
    --pure=true / --PURE slip straight past this refusal."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/opencode")
    assert cli.main(["setup"]) == 0
    assert cli.main([token]) == 2
    assert "disables" in capsys.readouterr().err


def test_launcher_forwards_a_real_opencode_subcommand(tmp_path, monkeypatch):
    """Regression: argparse's subparsers only recognized {setup, doctor,
    evaluate} -- any other first token (a real OpenCode subcommand like
    "run" or "chat") crashed with SystemExit("invalid choice: ...") instead
    of being forwarded, making the governed launcher unusable for its
    primary documented use case."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/opencode")
    assert cli.main(["setup"]) == 0
    captured = {}

    def _fake_call(argv, env=None):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(cli.subprocess, "call", _fake_call)
    assert cli.main(["run", "--auto", "fix", "this"]) == 0
    assert captured["argv"] == ["opencode", "run", "--auto", "fix", "this"]


def test_launcher_still_forwards_a_bare_flag_with_no_subcommand(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/opencode")
    assert cli.main(["setup"]) == 0
    captured = {}

    def _fake_call(argv, env=None):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(cli.subprocess, "call", _fake_call)
    assert cli.main([]) == 0
    assert captured["argv"] == ["opencode"]


def test_setup_and_doctor_still_dispatch_correctly_after_the_fix(tmp_path, monkeypatch, capsys):
    """The known-subcommand fast path must not break setup/doctor/evaluate
    themselves."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/opencode")
    assert cli.main(["setup", "--dry-run"]) == 0
    assert "would install" in capsys.readouterr().out
    assert cli.main(["doctor"]) == 1  # not actually installed yet (dry-run)
