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
    # _hermes_home() honors HERMES_HOME (shared with cmd_doctor); an exported
    # HERMES_HOME (e.g. inside a Hermes agent session) would make detection
    # see a real install that only exists on the host, not in the fixture.
    monkeypatch.delenv("HERMES_HOME", raising=False)


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

    def test_detects_hermes_via_hermes_home_env_var(self, monkeypatch, tmp_path, no_pip_calls, capsys):
        """`doctor` already honored HERMES_HOME; `setup`'s own detection used
        to hardcode ~/.hermes, so the two commands disagreed about whether
        Hermes was installed on the same machine."""
        hermes_home = tmp_path / "custom-hermes-home"
        hermes_home.mkdir()
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))
        rc = main(["setup"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Hermes Agent detected: yes" in out


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

    def test_with_talaria_enables_hermes_plugin_without_prompting(self, monkeypatch, no_pip_calls, capsys):
        """talaria-guard only uses pre_tool_call/transform_tool_result hooks
        and never needs Hermes' separate built-in-tool-override permission --
        `hermes plugins enable` asks about that permission interactively
        unless told not to, which would otherwise make a "one-command"
        installer stop on an unrelated Y/N prompt in a real terminal."""
        monkeypatch.setattr("custodian.cli.cmd_setup.shutil.which", lambda name: "/usr/bin/hermes" if name == "hermes" else None)
        rc = main(["setup", "--with", "talaria"])
        assert rc == 0
        enable_calls = [c for c in no_pip_calls if c[:2] == ["hermes", "plugins"]]
        assert len(enable_calls) == 1
        assert enable_calls[0] == ["hermes", "plugins", "enable", "talaria-guard", "--no-allow-tool-override"]

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
    def test_confined_mode_fails_readiness_when_profile_is_unavailable(self, monkeypatch, capsys):
        monkeypatch.setenv("CUSTODIAN_EXECUTION_MODE", "confined")
        monkeypatch.setattr("custodian.sandbox.confined_sandbox_available", lambda: False)
        rc = main(["doctor"])
        out = capsys.readouterr().out
        assert rc == 1
        assert "Confined execution is unavailable" in out

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
        (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
        (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text("name: custodian-hermes-guard\n")
        (tmp_path / "talaria").mkdir()
        (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")
        rc = main(["doctor", "--profile", "hermes"])
        assert rc == 0
        assert "Ready" in capsys.readouterr().out

    def test_hermes_plugin_check_resolves_active_hermes_profile(
        self, monkeypatch, tmp_path, capsys
    ):
        """Hermes stores plugins per named profile
        (~/.hermes/profiles/<name>/plugins/), not directly under
        ~/.hermes/plugins/ -- a real dev machine with an active "dev"
        profile had its correctly-installed, enabled plugin reported as
        missing because this check only looked at the bare default path."""
        real_find_spec = __import__("importlib").util.find_spec
        monkeypatch.setattr(
            "custodian.cli.cmd_doctor.importlib.util.find_spec",
            lambda name: object() if name == "talaria" else real_find_spec(name),
        )
        monkeypatch.setattr("custodian.cli.cmd_doctor.shutil.which", lambda name: None)
        hermes_home = tmp_path / ".hermes"
        (hermes_home / "active_profile").parent.mkdir(parents=True)
        (hermes_home / "active_profile").write_text("dev\n")
        profile_dir = hermes_home / "profiles" / "dev"
        (profile_dir / "plugins" / "talaria-guard").mkdir(parents=True)
        (profile_dir / "plugins" / "talaria-guard" / "plugin.yaml").write_text("name: guard\n")
        (profile_dir / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
        (profile_dir / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text("name: custodian-hermes-guard\n")
        monkeypatch.setenv("HERMES_HOME", "")
        monkeypatch.delenv("HERMES_HOME", raising=False)
        monkeypatch.setattr("custodian.cli.cmd_doctor.Path.home", lambda: tmp_path)
        monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
        (tmp_path / "talaria").mkdir()
        (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")

        rc = main(["doctor", "--profile", "hermes"])
        out = capsys.readouterr().out
        assert "Hermes plugin is missing" not in out
        assert str(profile_dir) in out
        assert rc == 0
        assert "Ready" in out

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
        (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
        (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text("name: custodian-hermes-guard\n")
        (tmp_path / "talaria").mkdir()
        (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")
        rc = main(["doctor", "--profile", "hermes"])
        assert rc == 1
        assert "not enabled" in capsys.readouterr().out

    def test_hermes_plugin_list_failure_is_reported_distinctly(
        self, monkeypatch, tmp_path, capsys
    ):
        """A broken/erroring `hermes` CLI must not be reported as 'installed
        but not enabled' -- that message previously covered both cases, which
        sends a troubleshooter chasing the wrong problem."""
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
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 2, "", "config corrupted"),
        )
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
        monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
        (tmp_path / "hermes" / "plugins" / "talaria-guard").mkdir(parents=True)
        (tmp_path / "hermes" / "plugins" / "talaria-guard" / "plugin.yaml").write_text("name: guard\n")
        (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
        (tmp_path / "hermes" / "plugins" / "custodian-hermes-guard" / "plugin.yaml").write_text("name: custodian-hermes-guard\n")
        (tmp_path / "talaria").mkdir()
        (tmp_path / "talaria" / "policy.yaml").write_text("{}\n")
        rc = main(["doctor", "--profile", "hermes"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "hermes plugins list" in out
        assert "config corrupted" in out
        assert "installed but not enabled" not in out
