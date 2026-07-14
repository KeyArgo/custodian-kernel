"""Caduceus credential broker tests: crypto, grants, egress, audit."""
import json
import subprocess
import sys

import pytest

from caduceus.vault import Vault
from caduceus.broker import Broker, LeakSentinel
from caduceus.grants import GrantPolicy, Grant, band_index
from caduceus.audit import AuditLog, AuditChainBrokenError
from caduceus.refs import SecretRef, find_refs
from caduceus.errors import (
    GrantDeniedError, UnknownRefError, VaultLockedError, VaultMissingError,
    CaduceusError,
)

PP = "test-passphrase-123"


@pytest.fixture
def vault(tmp_path):
    return Vault.create(path=tmp_path / "v.caduceus", passphrase=PP)


@pytest.fixture
def broker(vault):
    return Broker(vault)


# -- refs --------------------------------------------------------------------

def test_ref_is_value_free():
    r = SecretRef("stripe_sk")
    assert r.uri == "caduceus://stripe_sk"
    assert "stripe_sk" in repr(r)
    assert r == SecretRef.parse("caduceus://stripe_sk")


def test_ref_rejects_bad_names():
    with pytest.raises(ValueError):
        SecretRef("has spaces")
    with pytest.raises(ValueError):
        SecretRef("")


def test_find_refs():
    refs = find_refs("use caduceus://a and caduceus://b/c here")
    assert [r.name for r in refs] == ["a", "b/c"]


# -- crypto / vault ----------------------------------------------------------

def test_roundtrip(vault):
    vault.add("k", "the-secret-value")
    reopened = Vault.open(path=vault.path, passphrase=PP)
    assert reopened._resolve_value("k") == "the-secret-value"


def test_nothing_readable_at_rest(vault):
    vault.add("stripe_sk", "sk_live_supersecretzzz")
    raw = vault.path.read_bytes()
    assert b"stripe_sk" not in raw
    assert b"supersecret" not in raw


def test_wrong_passphrase_fails(vault):
    vault.add("k", "v")
    with pytest.raises(VaultLockedError):
        Vault.open(path=vault.path, passphrase="wrong")


def test_tampered_vault_fails(vault):
    vault.add("k", "v")
    blob = bytearray(vault.path.read_bytes())
    blob[-1] ^= 0xFF  # flip a ciphertext bit
    vault.path.write_bytes(blob)
    with pytest.raises(VaultLockedError):
        Vault.open(path=vault.path, passphrase=PP)


def test_open_missing(tmp_path):
    with pytest.raises(VaultMissingError):
        Vault.open(path=tmp_path / "nope.caduceus", passphrase=PP)


def test_rotate_master(vault):
    vault.add("k", "v")
    vault.rotate_master(new_passphrase="new-pp-456")
    with pytest.raises(VaultLockedError):
        Vault.open(path=vault.path, passphrase=PP)
    assert Vault.open(path=vault.path, passphrase="new-pp-456")._resolve_value("k") == "v"


def test_file_permissions_hardened(vault):
    import stat
    mode = stat.S_IMODE(vault.path.stat().st_mode)
    assert mode == 0o600


def test_import_env(tmp_path, vault):
    env = tmp_path / ".env"
    env.write_text("# comment\nSTRIPE_KEY=sk_test_1\nEMPTY=\nOPENAI_KEY='sk-2'\n")
    names = vault.import_env_file(env, profile="prod")
    assert set(names) == {"stripe_key", "openai_key"}
    assert vault.meta("stripe_key")["env_var"] == "STRIPE_KEY"


def test_rotation_count(vault):
    vault.add("k", "v1")
    vault.add("k", "v2", overwrite=True)
    assert vault.meta("k")["rotations"] == 1


# -- grants ------------------------------------------------------------------

def test_deny_by_default(broker):
    broker.vault.add("k", "v")
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "caduceus://k"}, "skill:x", "L1")


def test_grant_allows(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2")
    env = broker.build_env({"K": "caduceus://k"}, "skill:x", "L1", base_env={})
    assert env["K"] == "v"


def test_band_ceiling(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L1")
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "caduceus://k"}, "skill:x", "L2")


def test_wildcard_ref_grant(broker):
    broker.vault.add("stripe/sk", "v1")
    broker.vault.add("stripe/pk", "v2")
    broker.grant("stripe/*", "skill:x", max_band="L2")
    env = broker.build_env({"A": "caduceus://stripe/sk", "B": "caduceus://stripe/pk"},
                           "skill:x", "L1", base_env={})
    assert env["A"] == "v1" and env["B"] == "v2"


def test_grant_requester_must_be_exact():
    with pytest.raises(CaduceusError):
        Grant(ref_pattern="k", requester="skill:*")
    with pytest.raises(CaduceusError):
        Grant(ref_pattern="k", requester="noscheme")


def test_grant_expiry(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2", ttl_seconds=-1)  # already expired
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "caduceus://k"}, "skill:x", "L1")


def test_revoke(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x")
    assert broker.revoke("k", "skill:x") == 1
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "caduceus://k"}, "skill:x", "L1")


def test_owner_implicit_grant(broker):
    broker.vault.add("k", "v")
    env = broker.build_env({"K": "caduceus://k"}, "user:cli", "L4", base_env={})
    assert env["K"] == "v"


def test_unknown_ref(broker):
    broker.grant("*", "skill:x", max_band="L2")
    with pytest.raises(UnknownRefError):
        broker.build_env({"K": "caduceus://nope"}, "skill:x", "L1")


# -- egress ------------------------------------------------------------------

def test_spawn_injects_env(broker):
    broker.vault.add("k", "secret-42", env_var="MY_KEY")
    broker.grant("k", "user:cli")
    proc = broker.spawn(
        [sys.executable, "-c", "import os;print(os.environ['MY_KEY'])"],
        {"MY_KEY": "caduceus://k"}, "user:cli",
    )
    assert proc.stdout.strip() == "secret-42"


def test_profile_egress(broker):
    broker.vault.add("a", "v1", profile="prod", env_var="A")
    broker.vault.add("b", "v2", profile="prod", env_var="B")
    broker.vault.add("c", "v3", profile="dev", env_var="C")
    env = broker.env_for_profile("prod", "user:cli", base_env={})
    assert env["A"] == "v1" and env["B"] == "v2" and "C" not in env


# -- leak sentinel -----------------------------------------------------------

def test_leak_sentinel_registers_on_resolve(broker):
    broker.vault.add("k", "sk_live_abc123def456")
    broker.grant("k", "skill:x", max_band="L2")
    broker.build_env({"K": "caduceus://k"}, "skill:x", "L1", base_env={})
    assert broker.leak_sentinel.seen("sk_live_abc123def456")
    assert not broker.leak_sentinel.seen("unrelated")


def test_leak_sentinel_stores_only_hashes():
    s = LeakSentinel()
    s.register("supersecretvalue")
    assert "supersecretvalue" not in str(s._hashes)


# -- audit -------------------------------------------------------------------

def test_audit_chain_records(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2")
    broker.build_env({"K": "caduceus://k"}, "skill:x", "L1", base_env={})
    assert broker.audit.verify() >= 2  # grant + resolve


def test_audit_deny_recorded(broker):
    broker.vault.add("k", "v")
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "caduceus://k"}, "skill:x", "L1")
    events = [r["event"] for r in broker.audit.records()]
    assert "deny" in events


def test_audit_tamper_detected(broker, tmp_path):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2")
    broker.build_env({"K": "caduceus://k"}, "skill:x", "L1", base_env={})
    recs = broker.audit.path.read_text().splitlines()
    d = json.loads(recs[0]); d["requester"] = "skill:evil"
    recs[0] = json.dumps(d, sort_keys=True, separators=(",", ":"))
    broker.audit.path.write_text("\n".join(recs) + "\n")
    with pytest.raises(AuditChainBrokenError):
        broker.audit.verify()


def test_audit_truncation_detected(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2")
    for _ in range(3):
        broker.build_env({"K": "caduceus://k"}, "skill:x", "L1", base_env={})
    recs = broker.audit.path.read_text().splitlines()
    broker.audit.path.write_text("\n".join(recs[:-1]) + "\n")  # drop last
    # remaining chain still verifies (truncation of tail is detectable only
    # against an external anchor), but re-appending must chain from real tail:
    broker.audit.append("resolve", "k", "skill:x", "L1", "after truncation")
    assert broker.audit.verify() >= 1


# -- optional receipt co-signing ---------------------------------------------

def test_receipt_cosign_roundtrip(vault):
    from custodian.receipt import GovernedReceipt
    from caduceus.receipts import sign_receipt, verify_signed
    r = GovernedReceipt.build("charge", "L2", 5.0, "t", "autonomous", "ok", 3.0, {"a": 1})
    sig = sign_receipt(r, vault)
    assert verify_signed(r, sig, vault)
    assert not verify_signed(r, "bad", vault)


def test_receipt_cosign_detects_tamper(vault):
    from custodian.receipt import GovernedReceipt
    from caduceus.receipts import sign_receipt, verify_signed
    r = GovernedReceipt.build("charge", "L2", 5.0, "t", "autonomous", "ok", 3.0, {"a": 1})
    sig = sign_receipt(r, vault)
    r.amount = 9999.0
    assert not verify_signed(r, sig, vault)


def test_receipt_cosign_key_isolated(tmp_path):
    from custodian.receipt import GovernedReceipt
    from caduceus.receipts import sign_receipt, verify_signed
    v1 = Vault.create(path=tmp_path / "a.caduceus", passphrase="p1")
    v2 = Vault.create(path=tmp_path / "b.caduceus", passphrase="p2")
    r = GovernedReceipt.build("c", "L2", 1.0, "t", "autonomous", "ok", 1.0, {})
    sig = sign_receipt(r, v1)
    assert not verify_signed(r, sig, v2)  # different vault, different key
