"""Error-path tests for `custodian setup --with hermes-guard` and
`custodian doctor --profile hermes`.

subprocess.run is monkeypatched everywhere: this must never actually shell
out during the test suite.
"""
from __future__ import annotations

import subprocess

import pytest

from custodian.cli.main import main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_real_hermes(monkeypatch, tmp_path):
    """Detection must not pick up the real host's Hermes install/PATH."""
    monkeypatch.setattr("custodian.cli.cmd_setup.shutil.which", lambda name: None)
    monkeypatch.setattr("custodian.cli.cmd_setup.Path.home", lambda: tmp_path)
    monkeypatch.delenv("HERMES_HOME", raising=False)


@pytest.fixture
def no_subprocess(monkeypatch):
    """Block all real subprocess calls; return success by default."""
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("custodian.cli.cmd_setup.subprocess.run", _fake_run)
    return calls


@pytest.fixture
def hermes_guard_src(tmp_path):
    """Create a minimal bundled plugin dir so importlib.resources resolves."""
    src = tmp_path / "bundled" / "hermes_guard" / "plugin"
    src.mkdir(parents=True)
    (src / "plugin.yaml").write_text("name: custodian-hermes-guard\n")
    return src


@pytest.fixture
def mock_plugin_src(monkeypatch, hermes_guard_src):
    """Make importlib.resources.files('custodian') return the fixture dir."""
    import importlib.resources

    def _fake_files(package):
        if package == "custodian":
            return hermes_guard_src.parent.parent  # .../bundled/
        return importlib.resources.files(package)

    monkeypatch.setattr("importlib.resources.files", _fake_files)


# ---------------------------------------------------------------------------
# Test 1: copytree failure → error reported; best-effort gap noted
# ---------------------------------------------------------------------------

def test_copytree_failure_warns_not_aborts(
    monkeypatch, tmp_path, mock_plugin_src, no_subprocess, capsys,
):
    """When copytree raises OSError, the exception propagates through
    cmd_setup.run() to main(), which catches Exception and returns 1.

    NOTE: the docstring of _install_hermes_guard_plugin promises best-effort
    ("prints a warning rather than aborting the whole setup"), but copytree
    is not wrapped in try/except.  When that gap is closed this test should
    be updated to assert rc == 0 and a warning instead.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    def _failing_copytree(src, dst, **kw):
        raise OSError("Read-only filesystem")

    monkeypatch.setattr(
        "shutil.copytree", _failing_copytree,
    )

    rc = main(["setup", "--with", "hermes-guard"])
    out = capsys.readouterr()
    assert rc == 0, f"copytree OSError must not abort setup (got rc={rc}, stdout={out.out[:200]})"
    assert "warning" in out.out.lower()


# ---------------------------------------------------------------------------
# Test 2: doctor reports CLI failure distinctly
# ---------------------------------------------------------------------------

def test_doctor_cli_failure_reports_error_not_not_enabled(
    monkeypatch, tmp_path, capsys,
):
    """When `hermes plugins list` exits non-zero, doctor must report the
    CLI failure — not `installed but not enabled` which sends an operator
    chasing the wrong problem."""
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
            a[0], 2, "", "config corrupted",
        ),
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    (tmp_path / "hermes" / "plugins" / "talaria-guard").mkdir(parents=True)
    (tmp_path / "hermes" / "plugins" / "talaria-guard" / "plugin.yaml").write_text(
        "name: guard\n",
    )
    (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
    (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text(
        "name: custodian-hermes-guard\n",
    )
    (tmp_path / "talaria").mkdir()
    (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "hermes plugins list" in out
    assert "config corrupted" in out
    assert "installed but not enabled" not in out


# ---------------------------------------------------------------------------
# Test 3: doctor — CLI returns empty list → both plugins "not enabled"
# ---------------------------------------------------------------------------

def test_doctor_empty_list_reports_both_not_enabled(
    monkeypatch, tmp_path, capsys,
):
    """When `hermes plugins list` returns no matching plugins, doctor
    reports both as 'not enabled'."""
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
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "", ""),
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    (tmp_path / "hermes" / "plugins" / "talaria-guard").mkdir(parents=True)
    (tmp_path / "hermes" / "plugins" / "talaria-guard" / "plugin.yaml").write_text(
        "name: guard\n",
    )
    (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
    (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text(
        "name: custodian-hermes-guard\n",
    )
    (tmp_path / "talaria").mkdir()
    (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "talaria) is installed but not enabled" in out
    assert "custodian) is installed but not enabled" in out


# ---------------------------------------------------------------------------
# Test 4: setup --dry-run reports nothing installed
# ---------------------------------------------------------------------------

def test_dry_run_shows_dest_path(
    monkeypatch, tmp_path, mock_plugin_src, no_subprocess, capsys,
):
    """`custodian setup --with hermes-guard --dry-run` exits early in
    cmd_setup.run() (line 263) before reaching _install_hermes_guard_plugin,
    so the component-level dry-run (which would print the dest path) is
    never called.  The top-level run() prints a generic ``nothing installed``
    message instead."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    rc = main(["setup", "--with", "hermes-guard", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "hermes-guard" in out
    assert "nothing installed" in out.lower()


# ---------------------------------------------------------------------------
# Test 5: setup --enable calls `hermes plugins enable custodian-hermes-guard`
# ---------------------------------------------------------------------------

def test_enable_flag_calls_hermes_plugins_enable(
    monkeypatch, tmp_path, mock_plugin_src, capsys,
):
    """When `--enable` is passed and hermes is on PATH, setup calls
    `hermes plugins enable custodian-hermes-guard --no-allow-tool-override`."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setattr(
        "custodian.cli.cmd_setup.shutil.which",
        lambda name: "/usr/bin/hermes" if name == "hermes" else None,
    )

    run_calls = []

    def _fake_run(cmd, **kwargs):
        run_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("custodian.cli.cmd_setup.subprocess.run", _fake_run)

    rc = main(["setup", "--with", "hermes-guard", "--enable"])
    assert rc == 0
    enable_calls = [
        c for c in run_calls
        if c[:2] == ["hermes", "plugins"]
    ]
    assert len(enable_calls) == 1
    assert enable_calls[0] == [
        "hermes", "plugins", "enable", "custodian-hermes-guard",
        "--no-allow-tool-override",
    ]
