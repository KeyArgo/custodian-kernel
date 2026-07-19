"""paladin as a git credential helper: git asks for a host's password, paladin
resolves the token from the encrypted vault — never a token in the git config,
in ~/.git-credentials, in a remote URL, or on a command line.

A credential helper must never break git, so every failure path (locked vault,
missing ref, no grant) prints nothing and exits 0 so git falls back cleanly.
"""
import io
import sys

import pytest

from paladin import git_credential as gc
from paladin.broker import Broker
from paladin.vault import Vault

PP = "test-passphrase-123"
TOKEN = "ghp_realtokenvalue_abcdef 1234567890"  # spaces/odd chars must survive


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(tmp_path))
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    v = Vault.create(path=tmp_path / "vault.paladin", passphrase=PP)
    v.add("github_token", TOKEN)
    v.save()
    Broker(v).grant("github_token", gc.GIT_REQUESTER, max_band="L0")
    return v


def _run(action, ref, git_input="protocol=https\nhost=github.com\n\n"):
    """Drive gc.run with git's stdin and capture what it writes to stdout."""
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(git_input)
    sys.stdout = io.StringIO()
    try:
        rc = gc.run(action, ref)
        return rc, sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def test_get_returns_the_token_in_git_format(vault):
    rc, out = _run("get", "github_token")
    assert rc == 0
    assert "password=" + TOKEN in out
    assert out.rstrip().endswith(TOKEN)  # value preserved exactly, spaces and all
    assert "username=" in out


def test_store_and_erase_are_noops(vault):
    for action in ("store", "erase"):
        rc, out = _run(action, "github_token")
        assert rc == 0 and out == ""  # paladin never writes git's own copy


def test_missing_ref_prints_nothing_and_exits_zero(vault):
    """git must fall back cleanly, not error."""
    rc, out = _run("get", "does_not_exist")
    assert rc == 0
    assert "password=" not in out


def test_locked_vault_falls_back_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(tmp_path))
    monkeypatch.delenv("PALADIN_PASSPHRASE", raising=False)
    monkeypatch.delenv("PALADIN_KEYFILE", raising=False)
    Vault.create(path=tmp_path / "vault.paladin", passphrase=PP).save()
    rc, out = _run("get", "github_token")
    assert rc == 0 and "password=" not in out  # no crash, git just gets nothing


def test_no_grant_denies_but_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(tmp_path))
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    v = Vault.create(path=tmp_path / "vault.paladin", passphrase=PP)
    v.add("github_token", TOKEN)
    v.save()  # NOTE: no grant to git:credential
    rc, out = _run("get", "github_token")
    assert rc == 0
    assert "password=" not in out  # deny-by-default holds; git falls back
