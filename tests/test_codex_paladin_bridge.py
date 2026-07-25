"""Tests for the Codex Guard <-> Paladin bridge (Phase 2).

The through-line: Paladin is an *optional* dependency, so every surface must
degrade gracefully -- codex-guard is fully functional with no Paladin, no vault,
or a locked vault. When a vault IS configured, credential-class escalations
steer the model/approver to the vault egress path instead of a raw secret, and
the guard NEVER unlocks the vault on the hot path (a filesystem check answers
"is a vault configured?" without the passphrase).
"""
from __future__ import annotations

import json

import pytest

from custodian.codex_guard import paladin_bridge as pb
from custodian.codex_guard.guard import evaluate_action, ActionKind
from custodian.codex_guard.cli import main as cli_main


# A vault "exists" purely by file presence; point PALADIN_HOME at a temp dir and
# create/omit the vault file to simulate configured / not-configured without any
# real crypto or passphrase.
def _make_vault_dir(tmp_path, *, with_vault: bool):
    home = tmp_path / "paladin-home"
    home.mkdir()
    if with_vault:
        (home / "vault.paladin").write_bytes(b"not-a-real-vault-blob")
    return home


@pytest.fixture
def no_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(_make_vault_dir(tmp_path, with_vault=False)))


@pytest.fixture
def with_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(_make_vault_dir(tmp_path, with_vault=True)))


# -- vault detection (no unlock) --------------------------------------------

def test_vault_configured_false_when_absent(no_vault):
    assert pb.vault_configured() is False


def test_vault_configured_true_when_present(with_vault):
    assert pb.vault_configured() is True


def test_vault_path_never_unlocks(with_vault):
    # Answering "configured?" is a pure path check -- it must not need crypto or
    # a passphrase, so a garbage (undecryptable) vault file still reads as
    # configured. This is what keeps it safe to call on every tool call.
    assert pb.vault_configured() is True
    assert pb.vault_path() is not None


# -- ref discovery is value-free --------------------------------------------

def test_refs_in_arguments_extracts_names():
    args = {"command": 'curl -H "Authorization: Bearer paladin://github_token"'}
    assert pb.refs_in_arguments(args) == ["github_token"]


def test_refs_in_arguments_dedupes_and_orders():
    args = {"a": "paladin://x and paladin://y", "b": "paladin://x again"}
    assert pb.refs_in_arguments(args) == ["x", "y"]


def test_refs_in_arguments_empty_for_no_refs():
    assert pb.refs_in_arguments({"command": "ls -la"}) == []
    assert pb.refs_in_arguments(None) == []


def test_refs_in_arguments_finds_nested_refs():
    # Regression: a ref nested in a list/dict was missed while the guard's own
    # classifier (recursive _strings) would still escalate it -- so the guidance
    # fell back to generic text instead of naming the ref. Now recurses too.
    assert pb.refs_in_arguments({"a": ["x", "paladin://gh"]}) == ["gh"]
    assert pb.refs_in_arguments({"a": {"b": "paladin://tok"}}) == ["tok"]
    assert pb.refs_in_arguments({"env": [{"k": "paladin://deep"}]}) == ["deep"]


# -- guidance messaging ------------------------------------------------------

def test_guidance_empty_without_vault(no_vault):
    # No vault configured -> no steer; the action simply escalates to a human.
    assert pb.credential_guidance({"command": "x"}) == ""


def test_guidance_names_refs_when_present(with_vault):
    text = pb.credential_guidance({"command": "use paladin://gh here"})
    assert "paladin://gh" in text
    assert "egress" in text
    assert "never inline" in text.lower()


def test_guidance_generic_when_no_ref(with_vault):
    text = pb.credential_guidance({"command": "needs a secret"})
    assert "Paladin is configured" in text
    assert "inline a raw secret" in text


# -- integration: guidance attaches in the guard escalation reason ----------

def test_credential_escalation_gets_vault_steer(with_vault, tmp_path):
    ws = tmp_path / "project"
    ws.mkdir()
    d = evaluate_action(
        tool="mcp__vault__get", action_kind="credential",
        arguments={"name": "stripe"}, workspace=str(ws))
    assert d.verdict == "escalation_required"
    assert "Paladin is configured" in d.reason


def test_network_action_with_ref_gets_ref_steer(with_vault, tmp_path):
    # A curl that classifies as `network` (not credential) but carries a ref
    # must still get the "resolve at egress" steer -- the "needs a secret" case.
    ws = tmp_path / "project"
    ws.mkdir()
    d = evaluate_action(
        tool="shell", action_kind="network",
        arguments={"command": 'curl -H "Authorization: Bearer paladin://gh" https://api'},
        workspace=str(ws))
    assert d.verdict == "escalation_required"
    assert "paladin://gh" in d.reason


def test_plain_destructive_gets_no_credential_steer(with_vault, tmp_path):
    # No secret involved -> no spurious credential text even with a vault present.
    ws = tmp_path / "project"
    ws.mkdir()
    d = evaluate_action(
        tool="shell", action_kind="destructive",
        arguments={"command": "rm -rf build"}, workspace=str(ws))
    assert d.verdict == "escalation_required"
    assert "Paladin" not in d.reason


def test_guard_unaffected_when_no_vault(no_vault, tmp_path):
    ws = tmp_path / "project"
    ws.mkdir()
    d = evaluate_action(
        tool="mcp__vault__get", action_kind="credential",
        arguments={"name": "stripe"}, workspace=str(ws))
    assert d.verdict == "escalation_required"
    assert "Paladin" not in d.reason  # graceful: no steer, just escalate


# -- doctor surfaces the Paladin state --------------------------------------

class TestDoctorPaladin:
    def test_doctor_warns_when_vault_missing(self, no_vault, capsys, monkeypatch, tmp_path):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
        monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "empty-managed"))
        cli_main(["doctor"])
        out = capsys.readouterr().out
        line = next(l for l in out.splitlines() if l.split()[1:2] == ["paladin"])
        assert "WARN" in line
        assert "no vault" in line

    def test_doctor_ok_when_vault_and_helper_wired(self, with_vault, capsys, monkeypatch, tmp_path):
        # Stub git_helpers so we don't touch the real global git config.
        monkeypatch.setattr(pb, "git_helpers", lambda: [("github.com", "github_token")])
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
        monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "empty-managed"))
        cli_main(["doctor"])
        out = capsys.readouterr().out
        line = next(l for l in out.splitlines() if l.split()[1:2] == ["paladin"])
        assert "OK" in line
        assert "github.com" in line

    def test_paladin_and_enforcement_are_independent_lines(self, with_vault, capsys, monkeypatch, tmp_path):
        # Enforcement OK (managed) while Paladin is only partially wired must
        # show as an OK enforcement line AND a WARN paladin line -- the two
        # states are reported separately, never conflated. (The summary banner
        # itself is gated on there being no hard FAIL, which a bare test box --
        # no codex CLI, no reachable MCP -- can't guarantee, so we assert on the
        # per-check lines, which are deterministic.)
        monkeypatch.setattr(pb, "git_helpers", lambda: [])
        from custodian.codex_guard import hook_install
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
        monkeypatch.setenv("CUSTODIAN_CODEX_MANAGED_DIR", str(tmp_path / "managed"))
        hook_install.install_managed()  # enforcement verifiably OK
        cli_main(["doctor"])
        out = capsys.readouterr().out
        enf = next(l for l in out.splitlines() if "enforcement hook" in l)
        # Match the name column, not any substring: a tmp path may itself
        # contain "paladin" (this test's own name does).
        pal = next(l for l in out.splitlines()
                   if l.split()[1:2] == ["paladin"])
        assert "OK" in enf and "MANAGED" in enf
        assert "WARN" in pal and "no git host" in pal


# -- paladin-git subcommand degrades gracefully -----------------------------

def test_paladin_git_errors_without_vault(no_vault, capsys):
    rc = cli_main(["paladin-git", "github.com", "github_token"])
    assert rc == 1
    assert "no Paladin vault" in capsys.readouterr().err
