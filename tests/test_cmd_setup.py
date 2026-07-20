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
        assert any("custodian-talaria[dashboard]>=0.1.0,<0.2" in c for c in no_pip_calls)
        assert any(c[-2:] == ["hermes", "install"] for c in no_pip_calls)
        assert any(c[-3:] == ["doctor", "--profile", "hermes"] for c in no_pip_calls)
        out = capsys.readouterr().out
        assert "talaria dashboard" in out

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

    def test_skip_configure_only_installs_package(self, no_pip_calls):
        rc = main(["setup", "--profile", "hermes", "--skip-configure"])
        assert rc == 0
        assert len(no_pip_calls) == 1
        assert no_pip_calls[0][1:4] == ["-m", "pip", "install"]

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


class TestDoctor:
    def test_base_install_is_ready_without_optional_talaria(self, monkeypatch, capsys):
        real_find_spec = __import__("importlib").util.find_spec
        monkeypatch.setattr(
            "custodian.cli.cmd_doctor.importlib.util.find_spec",
            lambda name: None if name == "talaria" else real_find_spec(name),
        )
        rc = main(["doctor"])
        assert rc == 0
        assert "Ready" in capsys.readouterr().out

    def test_hermes_profile_requires_talaria(self, monkeypatch, capsys):
        real_find_spec = __import__("importlib").util.find_spec
        monkeypatch.setattr(
            "custodian.cli.cmd_doctor.importlib.util.find_spec",
            lambda name: None if name == "talaria" else real_find_spec(name),
        )
        rc = main(["doctor", "--profile", "hermes"])
        assert rc == 1
        assert "Talaria is not installed" in capsys.readouterr().out

    def test_hermes_profile_checks_plugin_and_policy(self, monkeypatch, tmp_path, capsys):
        real_find_spec = __import__("importlib").util.find_spec
        monkeypatch.setattr(
            "custodian.cli.cmd_doctor.importlib.util.find_spec",
            lambda name: object() if name == "talaria" else real_find_spec(name),
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
        monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
        (tmp_path / "hermes" / "plugins" / "talaria-guard").mkdir(parents=True)
        (tmp_path / "hermes" / "plugins" / "talaria-guard" / "plugin.yaml").write_text("name: guard\n")
        (tmp_path / "talaria").mkdir()
        (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")
        rc = main(["doctor", "--profile", "hermes"])
        assert rc == 0
        assert "Ready" in capsys.readouterr().out

    def test_hermes_profile_requires_enabled_plugin_when_cli_exists(
        self, monkeypatch, tmp_path, capsys
    ):
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
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "not enabled user 0.1 talaria-guard\n", ""),
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
        monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
        (tmp_path / "hermes" / "plugins" / "talaria-guard").mkdir(parents=True)
        (tmp_path / "hermes" / "plugins" / "talaria-guard" / "plugin.yaml").write_text("name: guard\n")
        (tmp_path / "talaria").mkdir()
        (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")
        rc = main(["doctor", "--profile", "hermes"])
        assert rc == 1
        assert "not enabled" in capsys.readouterr().out
