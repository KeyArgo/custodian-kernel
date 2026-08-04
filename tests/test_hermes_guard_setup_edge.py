"""Edge-case tests for hermes-guard integration in ``custodian setup``.

Covers component resolution, profile bundling, plugin enablement,
and the --enable flag's effect on subprocess calls.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from custodian.cli.main import main


# ── Component resolution (dry-run) ───────────────────────────────────────


def test_hg_without_profile(capsys):
    """``--with hermes-guard`` (no --profile) resolves the component."""
    rc = main(["setup", "--with", "hermes-guard", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hermes-guard" in out
    assert "nothing installed" in out


def test_profile_hermes_sorted(capsys):
    """``--profile hermes`` resolves talaria + hermes-guard (sorted)."""
    rc = main(["setup", "--profile", "hermes", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "hermes-guard" in out
    assert "talaria" in out
    idx_hg = out.index("hermes-guard")
    idx_t = out.index("talaria")
    assert idx_hg < idx_t, (
        f"Expected sorted order hermes-guard before talaria, "
        f"got hg@{idx_hg} talaria@{idx_t}"
    )


# ── Doctor ───────────────────────────────────────────────────────────────


def test_doctor_both_enabled(monkeypatch, tmp_path, capsys):
    """Doctor --profile hermes passes when both plugins show 'enabled'."""
    real_find_spec = __import__("importlib").util.find_spec
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.importlib.util.find_spec",
        lambda name: object() if name == "talaria" else real_find_spec(name),
    )
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.shutil.which",
        lambda name: "/usr/bin/hermes" if name == "hermes" else None,
    )
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0],
            0,
            "enabled user 0.1 talaria-guard\n"
            "enabled user 0.1 custodian-hermes-guard\n",
            "",
        ),
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    (tmp_path / "hermes" / "plugins" / "talaria-guard").mkdir(parents=True)
    (tmp_path / "hermes" / "plugins" / "talaria-guard" / "plugin.yaml").write_text(
        "name: guard\n"
    )
    (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
    (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text(
        (Path(__file__).resolve().parent.parent / "custodian" / "hermes_guard" / "plugin" / "plugin.yaml").read_text()
    )
    (tmp_path / "talaria").mkdir()
    (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")

    rc = main(["doctor", "--profile", "hermes"])
    assert rc == 0
    assert "Ready" in capsys.readouterr().out


# ── --enable flag behaviour ──────────────────────────────────────────────


_HG_ENABLE_CMD = ["hermes", "plugins", "enable",
                  "custodian-hermes-guard", "--no-allow-tool-override"]


@pytest.fixture
def _hg_mocks(monkeypatch, tmp_path):
    """Mock environment so hermes-guard plugin install + enable can run."""
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("custodian.cli.cmd_setup.subprocess.run", _fake_run)
    monkeypatch.setattr(
        "custodian.cli.cmd_setup.shutil.which",
        lambda name: "/usr/bin/hermes" if name == "hermes" else None,
    )

    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.yaml").write_text("name: custodian-hermes-guard\n")

    class _FakeFiles:
        def joinpath(self, *args):
            return plugin_dir

    monkeypatch.setattr("importlib.resources.files",
                        lambda package: _FakeFiles())

    return calls


def test_hg_enable_calls_enable(_hg_mocks, capsys):
    """``--with hermes-guard --enable`` calls ``hermes plugins enable``."""
    rc = main(["setup", "--with", "hermes-guard", "--enable"])
    assert rc == 0
    enable_calls = [c for c in _hg_mocks if c[:3] == ["hermes", "plugins", "enable"]]
    assert len(enable_calls) >= 1, (
        f"No hermes plugins enable call in {_hg_mocks}"
    )
    assert _HG_ENABLE_CMD in enable_calls


def test_hg_no_enable_without_flag(_hg_mocks, capsys):
    """Setup does NOT call ``hermes plugins enable`` without ``--enable``."""
    rc = main(["setup", "--with", "hermes-guard"])
    assert rc == 0
    enable_calls = [c for c in _hg_mocks if c[:3] == ["hermes", "plugins", "enable"]]
    assert len(enable_calls) == 0, (
        f"Expected no enable call without --enable, got {enable_calls}"
    )
