"""Tests for the Codex PreToolUse enforcement hook and its installer.

Codex's hook contract (verified against the codex-cli 0.144.6 binary) is
deny-or-defer only: a hook may emit permissionDecision:"deny" (with a required
non-empty reason) or emit nothing (defer to Codex's normal flow). It cannot
force-allow or ask. So the through-line here mirrors the Claude guard's but with
that narrower vocabulary, and the single most important property is the same:
every abnormal path resolves to an explicit deny, never to a silent allow.
"""
import json

import pytest

from custodian.codex_guard import hook, hook_install
from custodian.codex_guard.approvals import ApprovalStore
from custodian.codex_guard.mcp_server import _state_dir


@pytest.mark.parametrize(("tool", "kind"), [
    ("read_file", "read"), ("list_dir", "read"), ("update_plan", "read"),
    ("apply_patch", "write"), ("write_file", "write"), ("edit_file", "write"),
    ("shell", "test"), ("bash", "test"), ("local_shell", "test"),
    ("web_search", "network"),
    ("mcp__stripe__create_charge", "governance"),
    ("some_future_tool", "governance"),
])
def test_classification(tool, kind):
    assert hook.classify_tool(tool) == kind


def event(tmp_path, **overrides):
    value = {
        "hook_event_name": "PreToolUse",
        "tool_name": "read_file",
        "tool_input": {"path": str(tmp_path / "x.py")},
        "cwd": str(tmp_path),
        "session_id": "sess-1",
    }
    value.update(overrides)
    return value


def _state(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(tmp_path / "state"))


def test_read_defers(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    action, _ = hook.decide(event(tmp_path))
    assert action == "defer"


def test_benign_shell_defers(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    action, _ = hook.decide(event(
        tmp_path, tool_name="shell", tool_input={"command": ["ls", "-la"]}))
    assert action == "defer"


def test_network_shell_denies_with_approve_instructions(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    action, reason = hook.decide(event(
        tmp_path, tool_name="shell", tool_input={"command": "git push origin main"}))
    assert action == "deny"
    assert "approve" in reason.lower()
    assert "--digest" in reason


def test_forbidden_path_denies(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    action, _ = hook.decide(event(
        tmp_path, tool_name="apply_patch",
        tool_input={"path": "~/.ssh/authorized_keys", "content": "k"}))
    assert action == "deny"


def test_guard_self_protection_denies_codex_config_writes(tmp_path, monkeypatch):
    """The guard must fence writes to its own config, incl. bash redirects, so a
    tool call can't disable enforcement."""
    _state(monkeypatch, tmp_path)
    action, _ = hook.decide(event(
        tmp_path, tool_name="shell",
        tool_input={"command": "echo x >> ~/.codex/config.toml"}))
    assert action == "deny"


def test_newline_destructive_is_not_autonomous(tmp_path, monkeypatch):
    """Regression for the fixed newline-separator bypass, exercised through the
    real hook path."""
    _state(monkeypatch, tmp_path)
    action, _ = hook.decide(event(
        tmp_path, tool_name="shell",
        tool_input={"command": "echo hi\nshred -u secret.key"}))
    assert action == "deny"


@pytest.mark.parametrize("bad_event", [
    {}, {"tool_name": ""}, {"tool_name": 123}, "not-a-dict",
    {"tool_name": "read_file", "tool_input": {"path": "x"}, "cwd": ""},
])
def test_malformed_events_fail_closed(bad_event, tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    action, reason = hook.decide(bad_event)
    assert action == "deny"
    assert reason  # Codex requires a non-empty reason with a deny


@pytest.mark.parametrize("bad_session_id", [None, "", 42, []])
def test_missing_session_id_fails_closed(bad_session_id, tmp_path, monkeypatch):
    """A previous version fell back to the literal "unknown" for a missing
    session_id, which let two unrelated sessions that both omitted it share
    one requester identity and cross-consume each other's digest-bound
    approvals. session_id is a documented field in the real Codex event
    (verified against the codex-cli binary), so treat a missing one as the
    same kind of anomaly as a missing tool name: fail closed, not shared."""
    _state(monkeypatch, tmp_path)
    action, reason = hook.decide(event(tmp_path, session_id=bad_session_id))
    assert action == "deny"
    assert "session_id" in reason


def test_hook_main_emits_valid_deny_on_garbage(tmp_path, monkeypatch, capsys):
    _state(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin("not json"))
    rc = hook.main()
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    hso = out["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"]  # non-empty, as Codex requires


def test_hook_main_emits_nothing_on_defer(tmp_path, monkeypatch, capsys):
    _state(monkeypatch, tmp_path)
    monkeypatch.setattr("sys.stdin", _FakeStdin(json.dumps(event(tmp_path))))
    rc = hook.main()
    assert rc == 0
    assert capsys.readouterr().out == ""  # empty output = defer to normal flow


class _FakeStdin:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text


# --- escalation -> out-of-band approve -> identical re-run -> single use ------

def test_digest_bound_approval_lifecycle(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    ev = event(tmp_path, tool_name="shell",
               tool_input={"command": "git push origin main"}, session_id="s7")

    # 1) first attempt denies and surfaces an approval id + digest
    action, reason = hook.decide(ev)
    assert action == "deny"
    import re
    approval_id = re.search(r"approve (\S+) ", reason).group(1)
    digest = re.search(r"--digest (\S+)", reason).group(1)

    # 2) operator approves out of band (what the interactive terminal does)
    ApprovalStore(_state_dir()).approve(approval_id, approved_by="dev",
                                        expected_digest=digest)

    # 3) the identical re-run is now allowed exactly once
    assert hook.decide(ev)[0] == "defer"
    # 4) replay is denied -- the approval was single-use
    assert hook.decide(ev)[0] == "deny"


def test_approval_does_not_transfer_to_a_different_action(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    ev = event(tmp_path, tool_name="shell",
               tool_input={"command": "git push origin main"}, session_id="s8")
    action, reason = hook.decide(ev)
    import re
    approval_id = re.search(r"approve (\S+) ", reason).group(1)
    digest = re.search(r"--digest (\S+)", reason).group(1)
    ApprovalStore(_state_dir()).approve(approval_id, approved_by="dev", expected_digest=digest)
    # A *different* command must not be covered by that approval.
    other = event(tmp_path, tool_name="shell",
                  tool_input={"command": "git push origin other"}, session_id="s8")
    assert hook.decide(other)[0] == "deny"


# --- installer ---------------------------------------------------------------

def _seed_config(path, body="[projects.\"/x\"]\ntrust_level = \"trusted\"\n"):
    path.write_text(body)
    return path


def test_install_merges_and_is_idempotent(tmp_path):
    cfg = _seed_config(tmp_path / "config.toml")
    hook_install.install(cfg, python="/opt/py/bin/python3")
    hook_install.install(cfg, python="/opt/py/bin/python3")
    import tomllib
    data = tomllib.loads(cfg.read_text())
    assert data["projects"]["/x"]["trust_level"] == "trusted"   # untouched
    assert len(data["hooks"]["PreToolUse"]) == 1                 # not duplicated
    cmd = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert cmd == "/opt/py/bin/python3 -m custodian.codex_guard.hook"


def test_status_detects_stale_interpreter(tmp_path):
    cfg = _seed_config(tmp_path / "config.toml")
    hook_install.install(cfg, python="/old/python")
    assert hook_install.status(cfg, python="/new/python")["interpreter_current"] is False
    assert hook_install.status(cfg, python="/old/python")["interpreter_current"] is True


def test_uninstall_removes_only_our_block(tmp_path):
    cfg = _seed_config(tmp_path / "config.toml")
    hook_install.install(cfg)
    assert hook_install.uninstall(cfg) is True
    text = cfg.read_text()
    assert hook_install.BEGIN not in text
    assert "trust_level" in text            # unrelated content preserved
    assert hook_install.uninstall(cfg) is False  # nothing left to remove


def test_install_refuses_to_clobber_invalid_toml(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("this is = not valid ][")
    with pytest.raises(hook_install.HookInstallError):
        hook_install.install(cfg)
    assert cfg.read_text() == "this is = not valid ]["  # left untouched


def test_install_produces_parseable_toml(tmp_path):
    import tomllib
    cfg = _seed_config(tmp_path / "config.toml")
    hook_install.install(cfg)
    tomllib.loads(cfg.read_text())  # must not raise


# --- managed (always-on, unstrippable) install -------------------------------

def test_managed_install_writes_hook_and_lock(tmp_path, monkeypatch):
    import tomllib
    monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "etc-codex"))
    cfg, req = hook_install.install_managed(python="/opt/py/bin/python3")
    data = tomllib.loads(cfg.read_text())
    assert len(data["hooks"]["PreToolUse"]) == 1
    assert req is not None and "allow_managed_hooks_only = true" in req.read_text()
    st = hook_install.managed_status()
    assert st["installed"] and st["locked"]


def test_managed_install_idempotent_and_lock_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "etc-codex"))
    hook_install.install_managed()
    hook_install.install_managed()
    import tomllib
    cfg = tmp_path / "etc-codex" / "managed_config.toml"
    assert len(tomllib.loads(cfg.read_text())["hooks"]["PreToolUse"]) == 1
    req = (tmp_path / "etc-codex" / "requirements.toml").read_text()
    assert req.count("allow_managed_hooks_only") == 1


def test_managed_status_absent_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "empty"))
    assert hook_install.managed_status()["installed"] is False


def test_managed_uninstall_escape_hatch(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "etc-codex"))
    hook_install.install_managed()
    assert hook_install.managed_status()["installed"] is True
    assert hook_install.uninstall_managed() is True
    st = hook_install.managed_status()
    assert st["installed"] is False and st["locked"] is False
    assert hook_install.uninstall_managed() is False  # nothing left


def test_managed_uninstall_preserves_other_managed_config(tmp_path, monkeypatch):
    mdir = tmp_path / "etc-codex"
    monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(mdir))
    mdir.mkdir()
    (mdir / "managed_config.toml").write_text('[telemetry]\nenabled = true\n')
    hook_install.install_managed()
    hook_install.uninstall_managed()
    remaining = (mdir / "managed_config.toml").read_text()
    assert "telemetry" in remaining and hook_install.BEGIN not in remaining


@pytest.mark.parametrize(("platform", "expected_tail"), [
    ("linux", "/etc/codex"),
    ("darwin", "/etc/codex"),
])
def test_managed_dir_posix_default(platform, expected_tail, monkeypatch):
    monkeypatch.delenv("CUSTODIAN_CODEX_MANAGED_DIR", raising=False)
    monkeypatch.setattr("sys.platform", platform)
    assert str(hook_install.managed_dir()) == expected_tail


def test_managed_dir_windows_default(monkeypatch):
    monkeypatch.delenv("CUSTODIAN_CODEX_MANAGED_DIR", raising=False)
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("PROGRAMDATA", r"C:\ProgramData")
    assert hook_install.managed_dir().name == "Codex"


def test_managed_dir_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "custom"))
    assert hook_install.managed_dir() == tmp_path / "custom"
