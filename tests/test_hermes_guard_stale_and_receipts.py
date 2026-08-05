"""Error-path tests for the stale-plugin check and receipt store failures.

These complete the productization error-path matrix:
- stale deployed plugin.yaml is detected by the doctor (mismatch with the
  shipped version), rather than passing as "enforcement verified";
- a failing receipt store fails closed in the guard runtime (a decision is
  never silently accepted when the receipt chain cannot be written).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from custodian.cli.main import main

_SHIPPED_YAML = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "hermes_guard" / "plugin" / "plugin.yaml"
).read_text()


@pytest.fixture(autouse=True)
def no_real_hermes(monkeypatch, tmp_path):
    """Detection must not pick up the real host's Hermes install/PATH."""
    monkeypatch.setattr("custodian.cli.cmd_doctor.shutil.which", lambda name: None)
    monkeypatch.setattr("custodian.cli.cmd_doctor.Path.home", lambda: tmp_path)
    monkeypatch.delenv("HERMES_HOME", raising=False)


def _hermes_env(monkeypatch, tmp_path, talaria_policy: bool = True) -> Path:
    """Build the standard mocked Hermes environment; return plugin dir."""
    real_find_spec = __import__("importlib").util.find_spec
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.importlib.util.find_spec",
        lambda name: object() if name == "talaria" else real_find_spec(name),
    )
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    hermes = tmp_path / "hermes"
    (hermes / "plugins" / "talaria-guard").mkdir(parents=True)
    (hermes / "plugins" / "talaria-guard" / "plugin.yaml").write_text("name: guard\n")
    (hermes / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
    (talaria := tmp_path / "talaria").mkdir(exist_ok=True)
    if talaria_policy:
        (talaria / "policy.yaml").write_text("{}\n")
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    return hermes / "plugins" / "custodian-hermes-guard"


def test_stale_plugin_yaml_fails_enforcement_check(monkeypatch, tmp_path, capsys):
    """A deployed plugin.yaml that differs from the shipped version fails the
    enforcement check with a clear 'rerun setup' instruction."""
    plugin_dir = _hermes_env(monkeypatch, tmp_path)
    (plugin_dir / "plugin.yaml").write_text(
        "name: custodian-hermes-guard\nversion: \"9.9.9\"\n"
    )

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "differs from the shipped version" in out
    assert "custodian setup --profile hermes" in out


def test_matching_plugin_yaml_passes_enforcement_check(monkeypatch, tmp_path, capsys):
    """The identical shipped plugin.yaml passes the enforcement check."""
    plugin_dir = _hermes_env(monkeypatch, tmp_path)
    (plugin_dir / "plugin.yaml").write_text(_SHIPPED_YAML)

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Ready" in out


def test_doctor_ready_with_both_plugins_enabled(monkeypatch, tmp_path, capsys):
    """Full happy path: both plugins enabled via `hermes plugins list`."""
    plugin_dir = _hermes_env(monkeypatch, tmp_path)
    (plugin_dir / "plugin.yaml").write_text(_SHIPPED_YAML)
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.shutil.which",
        lambda name: "/usr/bin/hermes" if name == "hermes" else None,
    )
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0,
            "enabled user 0.1 talaria-guard\n"
            "enabled user 0.1 custodian-hermes-guard\n",
            "",
        ),
    )

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Ready" in out


def test_consume_failure_fails_closed(monkeypatch, tmp_path):
    """If consume() cannot write its claim marker (e.g. read-only approval
    store), wait_for_approval must resolve to a denied decision, never an
    approval that silently leaked through."""
    from custodian.hermes_guard.runtime import HermesGuardRuntime
    from custodian.codex_guard.approvals import ApprovalStore

    runtime = HermesGuardRuntime()
    store = ApprovalStore(runtime._state_dir)

    digest = "a" * 64
    rec = store.request(
        digest=digest, requester="hermes:test", ttl_seconds=60, harness="hermes"
    )
    store.approve(rec.approval_id, approved_by="operator")

    def _boom(*a, **kw):
        raise OSError("read-only approval store")

    monkeypatch.setattr(
        "custodian.hermes_guard.runtime.os.open", _boom
    )

    decision = runtime.wait_for_approval(
        tool_name="write_file",
        args={"path": str(tmp_path / "evil.md"), "content": "x"},
        approval_id=rec.approval_id,
        requester="hermes:test",
        timeout_seconds=0.5,
    )
    assert decision.verdict == "denied"
    assert "store failure" in decision.reason or "ApprovalError" in decision.reason
