"""`custodian setup` -- component orchestration installer.

subprocess.run is monkeypatched everywhere: this must never actually shell
out to pip during the test suite.
"""
from __future__ import annotations

import subprocess

import pytest

from custodian.cli.main import main


@pytest.fixture(autouse=True)
def no_real_hermes(monkeypatch, tmp_path):
    """Detection must not pick up the real host's Hermes install/PATH."""
    monkeypatch.setattr("custodian.cli.cmd_setup.shutil.which", lambda name: None)
    monkeypatch.setattr("custodian.cli.cmd_setup.Path.home", lambda: tmp_path)


@pytest.fixture
def no_pip_calls(monkeypatch):
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("custodian.cli.cmd_setup.subprocess.run", _fake_run)
    return calls


class TestDetectionOnly:
    def test_bare_setup_installs_nothing(self, no_pip_calls, capsys):
        rc = main(["setup"])
        assert rc == 0
        assert no_pip_calls == []
        assert "Nothing further to install" in capsys.readouterr().out

    def test_bare_setup_recommends_hermes_profile_when_detected(self, monkeypatch, tmp_path, no_pip_calls, capsys):
        monkeypatch.setattr("custodian.cli.cmd_setup.shutil.which", lambda name: "/usr/bin/hermes" if name == "hermes" else None)
        rc = main(["setup"])
        assert rc == 0
        assert no_pip_calls == []
        out = capsys.readouterr().out
        assert "Hermes Agent detected: yes" in out
        assert "custodian setup --profile hermes" in out


class TestDryRun:
    def test_dry_run_reports_without_installing(self, no_pip_calls, capsys):
        rc = main(["setup", "--with", "talaria", "--dry-run"])
        assert rc == 0
        assert no_pip_calls == []
        out = capsys.readouterr().out
        assert "talaria" in out
        assert "nothing installed" in out


class TestInstall:
    def test_with_talaria_installs_the_talaria_package(self, no_pip_calls, capsys):
        rc = main(["setup", "--with", "talaria"])
        assert rc == 0
        assert any("custodian-talaria" in " ".join(c) for c in no_pip_calls)
        out = capsys.readouterr().out
        assert "talaria hermes install" in out

    def test_with_paladin_alone_makes_no_pip_call(self, no_pip_calls, capsys):
        """paladin ships inside custodian-kernel's base install already."""
        rc = main(["setup", "--with", "paladin"])
        assert rc == 0
        assert no_pip_calls == []
        assert "already included" in capsys.readouterr().out

    def test_profile_hermes_installs_talaria(self, no_pip_calls):
        rc = main(["setup", "--profile", "hermes"])
        assert rc == 0
        assert any("custodian-talaria" in " ".join(c) for c in no_pip_calls)

    def test_profile_minimal_installs_nothing(self, no_pip_calls, capsys):
        rc = main(["setup", "--profile", "minimal"])
        assert rc == 0
        assert no_pip_calls == []

    def test_pip_failure_is_a_nonzero_exit(self, monkeypatch, capsys):
        def _fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1)

        monkeypatch.setattr("custodian.cli.cmd_setup.subprocess.run", _fake_run)
        rc = main(["setup", "--with", "talaria"])
        assert rc == 1
        assert "failed" in capsys.readouterr().out


class TestValidation:
    def test_unknown_component_is_an_error(self, no_pip_calls, capsys):
        rc = main(["setup", "--with", "nonexistent-thing"])
        assert rc == 1
        assert "unknown component" in capsys.readouterr().out

    def test_unknown_profile_is_an_error(self, no_pip_calls, capsys):
        rc = main(["setup", "--profile", "nonexistent-profile"])
        assert rc == 1
        assert "unknown profile" in capsys.readouterr().out
