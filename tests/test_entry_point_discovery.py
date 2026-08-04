"""Entry-point-based plugin discovery.

A separately-installed package (e.g. a future custodian-stripe) registers its
own skills (group "custodian.skills") and its own `custodian setup`
components/profiles (groups "custodian.setup_components" /
"custodian.setup_profiles") without the kernel's source ever being edited.

All discovery goes through importlib.metadata.entry_points, monkeypatched here
so no real installed package is needed. Invariants:

- Built-in names always win on a collision (paladin/talaria/hermes/minimal).
- A broken or malformed third-party entry point is skipped, never raised.
- This is additive: with nothing installed, behavior is identical to before.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from custodian.cli import cmd_setup
from custodian.tools.registry import ToolRegistry


class _FakeEntryPoint:
    def __init__(self, name, value=None, error=None):
        self.name = name
        self._value = value
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._value


def _install_fake_entry_points(monkeypatch, groups):
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group: list(groups.get(group, [])),
    )


def _write_skill(directory: Path, name: str, band: str = "L0") -> None:
    d = directory / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name}\n"
        f"metadata:\n  custodian:\n    band: {band}\n---\n"
    )


class TestToolRegistryEntryPointDiscovery:
    def test_explicit_extra_roots_merge_with_primary_root(self, tmp_path):
        primary = tmp_path / "primary"
        _write_skill(primary, "primary-tool")
        extra = tmp_path / "extra"
        _write_skill(extra, "extra-tool")
        reg = ToolRegistry(primary, extra_roots=[extra]).load()
        names = {t.name for t in reg.all()}
        assert names == {"primary-tool", "extra-tool"}

    def test_extra_roots_used_even_when_primary_root_empty(self, tmp_path):
        primary = tmp_path / "empty-primary"
        primary.mkdir()
        extra = tmp_path / "extra"
        _write_skill(extra, "extra-tool")
        reg = ToolRegistry(primary, extra_roots=[extra]).load()
        assert {t.name for t in reg.all()} == {"extra-tool"}

    def test_explicit_empty_extra_roots_skips_entry_point_discovery(self, monkeypatch, tmp_path):
        """extra_roots=[] is an explicit opt-out: discovery must not run at all."""

        def _boom(group):
            raise AssertionError("entry point discovery must not run with extra_roots=[]")

        monkeypatch.setattr("importlib.metadata.entry_points", _boom)
        _write_skill(tmp_path, "local-tool")
        reg = ToolRegistry(tmp_path, extra_roots=[]).load()
        assert {t.name for t in reg.all()} == {"local-tool"}

    def test_default_discovery_picks_up_valid_entry_point_root(self, monkeypatch, tmp_path):
        extra = tmp_path / "discovered"
        _write_skill(extra, "discovered-tool")
        _install_fake_entry_points(monkeypatch, {
            "custodian.skills": [_FakeEntryPoint("pkg", value=extra)],
        })
        reg = ToolRegistry(tmp_path).load()
        assert {t.name for t in reg.all()} == {"discovered-tool"}

    def test_broken_or_malformed_skill_entry_points_are_skipped(self, monkeypatch, tmp_path):
        _write_skill(tmp_path, "local-tool")
        missing_dir = tmp_path / "nonexistent"
        _install_fake_entry_points(monkeypatch, {
            "custodian.skills": [
                _FakeEntryPoint("raises", error=RuntimeError("broken import")),
                _FakeEntryPoint("not-a-path", value="definitely/not/a/path"),
                _FakeEntryPoint("missing-dir", value=missing_dir),
                _FakeEntryPoint("not-a-path-object", value=12345),
            ],
        })
        reg = ToolRegistry(tmp_path).load()
        assert {t.name for t in reg.all()} == {"local-tool"}


class TestCmdSetupEntryPointDiscovery:
    @pytest.fixture(autouse=True)
    def _no_real_hermes(self, monkeypatch, tmp_path):
        """Detection must not pick up the real host's Hermes install/PATH."""
        monkeypatch.setattr("custodian.cli.cmd_setup.shutil.which", lambda name: None)
        monkeypatch.setattr("custodian.cli.cmd_setup.Path.home", lambda: tmp_path)

    def test_discovered_component_and_profile_are_used(self, monkeypatch):
        _install_fake_entry_points(monkeypatch, {
            "custodian.setup_components": [
                _FakeEntryPoint(
                    "stripe",
                    {"description": "Stripe billing", "pip_spec": "custodian-stripe>=0.1"},
                ),
            ],
            "custodian.setup_profiles": [
                _FakeEntryPoint("payments", ["stripe"]),
            ],
        })
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile="payments", with_=None)
        ) == ["stripe"]
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile=None, with_="stripe")
        ) == ["stripe"]

    def test_discovered_component_installs_end_to_end(self, monkeypatch, capsys):
        calls = []

        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("custodian.cli.cmd_setup.subprocess.run", _fake_run)
        _install_fake_entry_points(monkeypatch, {
            "custodian.setup_components": [
                _FakeEntryPoint(
                    "stripe",
                    {"description": "Stripe billing", "pip_spec": "custodian-stripe>=0.1"},
                ),
            ],
        })
        from custodian.cli.main import main
        rc = main(["setup", "--with", "stripe", "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Stripe billing" in out
        assert "nothing installed" in out
        assert calls == []

    def test_builtin_component_wins_on_name_collision(self, monkeypatch):
        _install_fake_entry_points(monkeypatch, {
            "custodian.setup_components": [
                _FakeEntryPoint("paladin", {"description": "malicious", "pip_spec": "evil"}),
                _FakeEntryPoint("talaria", {"description": "malicious", "pip_spec": "evil"}),
            ],
        })
        eff = cmd_setup._effective_components()
        assert eff["paladin"]["description"] == (
            "Credential broker — vault, grants, egress (already included)"
        )
        assert eff["talaria"]["pip_spec"] == "custodian-talaria[dashboard]>=0.1.0,<0.2"
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile=None, with_="paladin")
        ) == ["paladin"]

    def test_builtin_profile_wins_on_name_collision(self, monkeypatch):
        _install_fake_entry_points(monkeypatch, {
            "custodian.setup_profiles": [
                _FakeEntryPoint("hermes", ["paladin"]),
                _FakeEntryPoint("minimal", ["talaria"]),
            ],
        })
        eff = cmd_setup._effective_profiles()
        assert eff["hermes"] == ["talaria", "hermes-guard"]
        assert eff["minimal"] == []
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile="hermes", with_=None)
        ) == ["hermes-guard", "talaria"]

    def test_malformed_setup_entry_points_are_skipped(self, monkeypatch):
        _install_fake_entry_points(monkeypatch, {
            "custodian.setup_components": [
                _FakeEntryPoint("not-a-dict", value=["paladin"]),
                _FakeEntryPoint("raises", error=RuntimeError("broken")),
            ],
            "custodian.setup_profiles": [
                _FakeEntryPoint("not-a-list", value={"a": 1}),
                _FakeEntryPoint("not-strs", value=[1, 2, 3]),
                _FakeEntryPoint("raises-too", error=RuntimeError("broken")),
            ],
        })
        assert "not-a-dict" not in cmd_setup._effective_components()
        assert "raises" not in cmd_setup._effective_components()
        profiles = cmd_setup._effective_profiles()
        assert "not-a-list" not in profiles
        assert "not-strs" not in profiles
        assert "raises-too" not in profiles
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile="hermes", with_=None)
        ) == ["hermes-guard", "talaria"]
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile=None, with_="paladin")
        ) == ["paladin"]

    def test_no_entry_points_installed_is_a_noop(self, monkeypatch):
        _install_fake_entry_points(monkeypatch, {})
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile=None, with_=None)
        ) == []
        assert cmd_setup._resolve_components(
            SimpleNamespace(profile="hermes", with_=None)
        ) == ["hermes-guard", "talaria"]
