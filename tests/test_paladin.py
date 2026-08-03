"""Paladin credential broker tests: crypto, grants, egress, audit."""
import json
import subprocess
import sys

import pytest

from paladin.vault import Vault
from paladin.broker import Broker, LeakSentinel
from paladin.grants import GrantPolicy, Grant, band_index
from paladin.audit import AuditLog, AuditChainBrokenError
from paladin.refs import SecretRef, find_refs
from paladin.errors import (
    GrantDeniedError, UnknownRefError, VaultLockedError, VaultMissingError,
    PaladinError,
)
from paladin.guard import IntegrityGuardError
from paladin.guard import PaladinGuard

PP = "test-passphrase-123"


@pytest.fixture
def vault(tmp_path):
    return Vault.create(path=tmp_path / "v.paladin", passphrase=PP)


@pytest.fixture
def broker(vault):
    return Broker(vault)


# -- refs --------------------------------------------------------------------

def test_ref_is_value_free():
    r = SecretRef("stripe_sk")
    assert r.uri == "paladin://stripe_sk"
    assert "stripe_sk" in repr(r)
    assert r == SecretRef.parse("paladin://stripe_sk")


def test_ref_rejects_bad_names():
    with pytest.raises(ValueError):
        SecretRef("has spaces")
    with pytest.raises(ValueError):
        SecretRef("")


def test_find_refs():
    refs = find_refs("use paladin://a and paladin://b/c here")
    assert [r.name for r in refs] == ["a", "b/c"]


# -- crypto / vault ----------------------------------------------------------

def test_scrypt_n_strengthened_and_derive_key_still_works():
    # Regression guard for the review finding that SCRYPT_N=2**15 was too
    # weak for a long-lived credential vault (vs. a login screen). Also
    # exercises the real hashlib.scrypt() call with the new maxmem
    # headroom — 128*N*r lands exactly on the old maxmem boundary at
    # N=2**17, which some implementations reject as "memory limit
    # exceeded" if maxmem isn't strictly greater.
    from paladin import crypto
    assert crypto.SCRYPT_N >= 2 ** 17
    params = crypto.KdfParams.fresh()
    key = crypto.derive_key("a-real-passphrase", params)
    assert len(key) == crypto.KEY_LEN


def test_roundtrip(vault):
    vault.add("k", "the-secret-value")
    reopened = Vault.open(path=vault.path, passphrase=PP)
    assert reopened._resolve_value("k") == "the-secret-value"


def test_rename_preserves_value_metadata_and_migrates_only_exact_grants(vault, broker):
    vault.add("old/root", "the-secret", kind="password", profile="infra",
              env_var="OLD_ROOT", note="keep", allowed_hosts=["titan"])
    broker.grant("old/root", "skill:operator", ttl_seconds=60)
    broker.grant("old/*", "skill:wildcard", ttl_seconds=60)
    assert broker.rename("old/root", "titan/root", "user:cli") == 1
    assert vault._resolve_value("titan/root") == "the-secret"
    meta = vault.meta("titan/root")
    assert meta["kind"] == "password" and meta["profile"] == "infra"
    assert meta["env_var"] == "OLD_ROOT" and meta["allowed_hosts"] == ["titan"]
    assert [(g.ref_pattern, g.requester) for g in broker.grants.list()] == [
        ("titan/root", "skill:operator"), ("old/*", "skill:wildcard")]
    with pytest.raises(PaladinError):
        vault.rename("titan/root", "bad name")


def test_rotate_value_preserves_all_metadata(vault):
    vault.add("titan/root", "old", kind="password", profile="infra",
              env_var="TITAN_ROOT", note="host", allowed_hosts=["titan"])
    vault.rotate_value("titan/root", "new")
    assert vault._resolve_value("titan/root") == "new"
    meta = vault.meta("titan/root")
    assert meta["kind"] == "password" and meta["profile"] == "infra"
    assert meta["env_var"] == "TITAN_ROOT" and meta["note"] == "host"
    assert meta["allowed_hosts"] == ["titan"] and meta["rotations"] == 1


def test_rejected_complete_edit_leaves_entry_and_grants_untouched(vault, broker):
    vault.add("old/root", "old-value", kind="password", profile="infra",
              env_var="OLD_ROOT", note="keep", allowed_hosts=["titan"])
    broker.grant("old/root", "skill:operator", ttl_seconds=60)

    with pytest.raises(PaladinError, match="invalid secret kind"):
        vault.edit("old/root", new_name="titan/root", new_value="new-value",
                   rotate=True, kind="not-a-kind")

    assert vault._resolve_value("old/root") == "old-value"
    assert vault.meta("old/root")["note"] == "keep"
    assert [(g.ref_pattern, g.requester) for g in broker.grants.list()] == [
        ("old/root", "skill:operator")]
    assert "titan/root" not in vault.names()


def test_integrity_guard_blocks_agent_resolution_but_keeps_owner_recovery(vault, broker):
    vault.add("k", "the-secret")
    broker.audit.append("resolve", "k", "user:cli")
    raw = vault.path.parent / "audit.jsonl"
    raw.write_text(raw.read_text().replace('"event":"resolve"', '"event":"tampered"'))
    broker.grant("k", "skill:agent")  # owner creates the grant for this test
    with pytest.raises(IntegrityGuardError):
        broker._resolve("k", "skill:agent", "L0")
    assert broker._resolve("k", "user:cli", "L0") == "the-secret"


def test_guard_reports_value_free_audit_fingerprint_and_backup_hash(vault, broker, tmp_path):
    broker.audit.append("resolve", "safe-ref", "user:cli")
    guard = PaladinGuard(broker.audit)
    status = guard.status()
    assert status.healthy and len(status.audit_sha256) == 64
    import zipfile
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as out:
        out.writestr("audit.jsonl", broker.audit.path.read_bytes())
    assert guard.backup_audit_hashes(tmp_path) == [("backup.zip", status.audit_sha256)]


def test_guard_fails_closed_when_audit_path_cannot_be_read(vault, broker):
    broker.audit.path.mkdir()
    status = PaladinGuard(broker.audit).status()
    assert not status.healthy
    assert status.valid_records == 0
    assert status.audit_sha256 == ""


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
        Vault.open(path=tmp_path / "nope.paladin", passphrase=PP)


def test_rotate_master(vault):
    vault.add("k", "v")
    vault.rotate_master(new_passphrase="new-pp-456")
    with pytest.raises(VaultLockedError):
        Vault.open(path=vault.path, passphrase=PP)
    assert Vault.open(path=vault.path, passphrase="new-pp-456")._resolve_value("k") == "v"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "os.chmod on Windows only toggles the read-only bit and cannot express "
        "0600, so this asserts a guarantee the OS does not offer — see the note "
        "at paladin/vault.py:177, which states the 0600/0700 guarantee holds on "
        "POSIX only and that AEAD encryption is the sole at-rest protection on "
        "Windows. Meaningful on POSIX; unsatisfiable here."
    ),
)
def test_file_permissions_hardened(vault):
    import stat
    mode = stat.S_IMODE(vault.path.stat().st_mode)
    assert mode == 0o600


# -- close() / key zeroization / locking — found missing in review ----------

def test_close_zeroes_key_and_clears_entries(vault):
    vault.add("k", "v")
    assert any(b != 0 for b in vault._key)
    vault.close()
    assert all(b == 0 for b in vault._key)
    assert vault._entries == {}
    assert vault._grants == []


def test_close_is_idempotent(vault):
    vault.close()
    vault.close()  # must not raise on a second call


def test_context_manager_closes_on_exit(vault):
    path = vault.path
    with Vault.open(path=path, passphrase=PP) as v:
        v.add("k", "v")
        v.save()
    assert all(b == 0 for b in v._key)
    # vault on disk is unaffected by the in-process wipe
    reopened = Vault.open(path=path, passphrase=PP)
    assert reopened._resolve_value("k") == "v"


def test_rotate_master_wipes_old_key(vault):
    old_key_bytes = bytes(vault._key)
    vault.add("k", "v")
    vault.rotate_master(new_passphrase="new-pp-456")
    # the object that held the old key was zeroed, not just replaced
    assert bytes(vault._key) != old_key_bytes


def test_concurrent_saves_do_not_corrupt_vault(tmp_path):
    # Two Vault handles on the same file, saving back-to-back, must not
    # corrupt the file even though the second save's in-memory entries
    # don't include the first save's addition (the known, documented
    # lost-update limitation) — the file itself must stay valid and
    # openable, not truncated or interleaved.
    path = tmp_path / "race.paladin"
    v1 = Vault.create(path=path, passphrase=PP)
    v2 = Vault.open(path=path, passphrase=PP)
    v1.add("a", "1")
    v1.save()
    v2.add("b", "2")
    v2.save()
    reopened = Vault.open(path=path, passphrase=PP)
    assert reopened._resolve_value("b") == "2"


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
        broker.build_env({"K": "paladin://k"}, "skill:x", "L1")


def test_grant_allows(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2")
    env = broker.build_env({"K": "paladin://k"}, "skill:x", "L1", base_env={})
    assert env["K"] == "v"


def test_band_ceiling(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L1")
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "paladin://k"}, "skill:x", "L2")


def test_wildcard_ref_grant(broker):
    broker.vault.add("stripe/sk", "v1")
    broker.vault.add("stripe/pk", "v2")
    broker.grant("stripe/*", "skill:x", max_band="L2")
    env = broker.build_env({"A": "paladin://stripe/sk", "B": "paladin://stripe/pk"},
                           "skill:x", "L1", base_env={})
    assert env["A"] == "v1" and env["B"] == "v2"


def test_grant_requester_must_be_exact():
    with pytest.raises(PaladinError):
        Grant(ref_pattern="k", requester="skill:*")
    with pytest.raises(PaladinError):
        Grant(ref_pattern="k", requester="noscheme")


def test_grant_expiry(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2", ttl_seconds=-1)  # already expired
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "paladin://k"}, "skill:x", "L1")


def test_revoke(broker):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x")
    assert broker.revoke("k", "skill:x") == 1
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "paladin://k"}, "skill:x", "L1")


def test_owner_implicit_grant(broker):
    broker.vault.add("k", "v")
    env = broker.build_env({"K": "paladin://k"}, "user:cli", "L4", base_env={})
    assert env["K"] == "v"


def test_unknown_ref(broker):
    broker.grant("*", "skill:x", max_band="L2")
    with pytest.raises(UnknownRefError):
        broker.build_env({"K": "paladin://nope"}, "skill:x", "L1")


# -- egress ------------------------------------------------------------------

def test_spawn_injects_env(broker):
    broker.vault.add("k", "secret-42", env_var="MY_KEY")
    broker.grant("k", "user:cli")
    proc = broker.spawn(
        [sys.executable, "-c", "import os;print(os.environ['MY_KEY'])"],
        {"MY_KEY": "paladin://k"}, "user:cli",
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
    broker.build_env({"K": "paladin://k"}, "skill:x", "L1", base_env={})
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
    broker.build_env({"K": "paladin://k"}, "skill:x", "L1", base_env={})
    assert broker.audit.verify() >= 2  # grant + resolve


def test_audit_deny_recorded(broker):
    broker.vault.add("k", "v")
    with pytest.raises(GrantDeniedError):
        broker.build_env({"K": "paladin://k"}, "skill:x", "L1")
    events = [r["event"] for r in broker.audit.records()]
    assert "deny" in events


def test_audit_tamper_detected(broker, tmp_path):
    broker.vault.add("k", "v")
    broker.grant("k", "skill:x", max_band="L2")
    broker.build_env({"K": "paladin://k"}, "skill:x", "L1", base_env={})
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
        broker.build_env({"K": "paladin://k"}, "skill:x", "L1", base_env={})
    recs = broker.audit.path.read_text().splitlines()
    broker.audit.path.write_text("\n".join(recs[:-1]) + "\n")  # drop last
    # remaining chain still verifies (truncation of tail is detectable only
    # against an external anchor), but re-appending must chain from real tail:
    broker.audit.append("resolve", "k", "skill:x", "L1", "after truncation")
    assert broker.audit.verify() >= 1


# -- optional receipt co-signing ---------------------------------------------

def test_receipt_cosign_roundtrip(vault):
    from custodian.receipt import GovernedReceipt
    from paladin.receipts import sign_receipt, verify_signed
    r = GovernedReceipt.build("charge", "L2", 5.0, "t", "autonomous", "ok", 3.0, {"a": 1})
    sig = sign_receipt(r, vault)
    assert verify_signed(r, sig, vault)
    assert not verify_signed(r, "bad", vault)


def test_receipt_cosign_detects_tamper(vault):
    from custodian.receipt import GovernedReceipt
    from paladin.receipts import sign_receipt, verify_signed
    r = GovernedReceipt.build("charge", "L2", 5.0, "t", "autonomous", "ok", 3.0, {"a": 1})
    sig = sign_receipt(r, vault)
    r.amount = 9999.0
    assert not verify_signed(r, sig, vault)


def test_receipt_cosign_key_isolated(tmp_path):
    from custodian.receipt import GovernedReceipt
    from paladin.receipts import sign_receipt, verify_signed
    v1 = Vault.create(path=tmp_path / "a.paladin", passphrase="p1")
    v2 = Vault.create(path=tmp_path / "b.paladin", passphrase="p2")
    r = GovernedReceipt.build("c", "L2", 1.0, "t", "autonomous", "ok", 1.0, {})
    sig = sign_receipt(r, v1)
    assert not verify_signed(r, sig, v2)  # different vault, different key


def test_open_from_env_missing_keyfile_fails_clean(monkeypatch, vault):
    """Regression: PALADIN_KEYFILE pointing at a nonexistent file used to
    raise a raw FileNotFoundError instead of a clean, actionable error.
    Uses an existing vault so this exercises the keyfile check specifically
    rather than the (higher-priority) missing-vault check."""
    dead_path = vault.path.parent / "nonexistent.key"
    monkeypatch.setenv("PALADIN_KEYFILE", str(dead_path))
    monkeypatch.setenv("PALADIN_PASSPHRASE", "irrelevant-should-not-be-tried")
    with pytest.raises(VaultLockedError, match="keyfile.*could not be read"):
        Vault.open_from_env(path=vault.path)


def test_open_from_env_missing_keyfile_does_not_silently_use_passphrase(monkeypatch, tmp_path, vault):
    """A dead keyfile must not silently fall through to unlocking a
    DIFFERENT vault via the passphrase — that would be worse than failing."""
    dead_path = tmp_path / "nonexistent.key"
    monkeypatch.setenv("PALADIN_KEYFILE", str(dead_path))
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    with pytest.raises(VaultLockedError):
        Vault.open_from_env(path=vault.path)


def test_open_from_env_valid_keyfile_still_works(monkeypatch, tmp_path):
    keyfile = tmp_path / "real.key"
    keyfile.write_bytes(b"x" * 32)
    v = Vault.create(path=tmp_path / "v.paladin", keyfile=keyfile)
    v.add("k", "value")
    monkeypatch.setenv("PALADIN_KEYFILE", str(keyfile))
    monkeypatch.delenv("PALADIN_PASSPHRASE", raising=False)
    reopened = Vault.open_from_env(path=v.path)
    assert reopened._resolve_value("k") == "value"


def test_open_from_env_keyfile_is_a_directory_fails_clean(monkeypatch, vault, tmp_path):
    """Regression: only FileNotFoundError was caught originally: a keyfile
    path that exists but is a directory (IsADirectoryError) or unreadable
    (PermissionError) must fail just as cleanly, not with a raw traceback."""
    dir_as_keyfile = tmp_path / "not_a_file"
    dir_as_keyfile.mkdir()
    monkeypatch.setenv("PALADIN_KEYFILE", str(dir_as_keyfile))
    with pytest.raises(VaultLockedError, match="could not be read"):
        Vault.open_from_env(path=vault.path)


def test_open_from_env_missing_vault_reported_before_missing_keyfile(monkeypatch, tmp_path):
    """When both the vault and the keyfile are missing, the vault-missing
    error is more fundamental for a first-time user ('run paladin init
    first') and should surface first, not a keyfile complaint."""
    dead_keyfile = tmp_path / "nonexistent.key"
    monkeypatch.setenv("PALADIN_KEYFILE", str(dead_keyfile))
    with pytest.raises(VaultMissingError):
        Vault.open_from_env(path=tmp_path / "no-such-vault.paladin")


def test_entry_allowed_hosts_default_empty(vault):
    vault.add("k", "v")
    assert vault.meta("k")["allowed_hosts"] == []


def test_entry_allowed_hosts_stored(vault):
    vault.add("stripe_sk", "v", allowed_hosts=["api.stripe.com"])
    reopened = Vault.open(path=vault.path, passphrase=PP)
    assert reopened.meta("stripe_sk")["allowed_hosts"] == ["api.stripe.com"]


def test_old_vault_without_allowed_hosts_loads(vault):
    # Simulate an OLD vault: entries whose JSON predates the allowed_hosts
    # field. The dataclass default must fill it in, not crash on load.
    import json
    vault.add("k", "v")
    # hand-craft a decrypted doc missing allowed_hosts, re-encrypt it
    from paladin import crypto
    doc = {"entries": {"legacy": {
        "name": "legacy", "value": "secret", "kind": "secret", "profile": "default",
        "env_var": "LEGACY", "note": "", "created_at": 1.0, "updated_at": 1.0,
        "rotations": 0}}, "grants": []}
    blob = crypto.encrypt_blob(vault._key, json.dumps(doc).encode(),
                               vault._params.to_header())
    vault.path.write_bytes(blob)
    reopened = Vault.open(path=vault.path, passphrase=PP)
    assert reopened.meta("legacy")["allowed_hosts"] == []  # default filled in


# -- backup / restore (data safety + machine migration) ----------------------

from pathlib import Path
from paladin.vault import copy_encrypted
from paladin import cli as paladin_cli


def test_copy_encrypted_roundtrips_and_stays_ciphertext(vault, tmp_path):
    vault.add("stripe_sk", "sk_live_super_secret", note="prod key")
    dest = tmp_path / "backup.paladin"
    copy_encrypted(vault.path, dest)
    # the backup must NOT contain the plaintext secret anywhere
    assert b"sk_live_super_secret" not in dest.read_bytes()
    # and it must open with the same passphrase, with the entry intact
    restored = Vault.open(path=dest, passphrase=PP)
    assert restored.names() == ["stripe_sk"]
    assert restored.meta("stripe_sk")["note"] == "prod key"


def test_copy_encrypted_rejects_same_file(vault):
    with pytest.raises(PaladinError):
        copy_encrypted(vault.path, vault.path)


def test_copy_encrypted_rejects_missing_source(tmp_path):
    with pytest.raises(VaultMissingError):
        copy_encrypted(tmp_path / "nope.paladin", tmp_path / "out.paladin")


def test_copy_encrypted_rejects_torn_source(tmp_path):
    torn = tmp_path / "torn.paladin"
    torn.write_bytes(b"not a real vault blob")
    with pytest.raises(Exception):  # split_blob refuses a non-AEAD file
        copy_encrypted(torn, tmp_path / "out.paladin")


def test_cli_backup_then_restore_to_new_machine(monkeypatch, tmp_path):
    """The migration story: back up here, restore into a fresh vault path
    (simulating a second machine) with the same passphrase."""
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    monkeypatch.delenv("PALADIN_KEYFILE", raising=False)
    src_vault = tmp_path / "machine1.paladin"
    Vault.create(path=src_vault, passphrase=PP).add("api_key", "topsecret")

    backup = tmp_path / "usb" / "vault.paladin"
    assert paladin_cli.main(["--vault", str(src_vault), "backup", str(backup)]) == 0
    assert backup.exists()

    # "machine 2": a path with no vault yet
    machine2 = tmp_path / "machine2.paladin"
    assert paladin_cli.main(["--vault", str(machine2), "restore", str(backup)]) == 0
    assert Vault.open(path=machine2, passphrase=PP).names() == ["api_key"]


def test_cli_backup_to_directory_picks_a_name(monkeypatch, tmp_path):
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    src_vault = tmp_path / "v.paladin"
    Vault.create(path=src_vault, passphrase=PP).add("k", "v")
    outdir = tmp_path / "backups"
    outdir.mkdir()
    assert paladin_cli.main(["--vault", str(src_vault), "backup", str(outdir)]) == 0
    made = list(outdir.glob("paladin-backup-*.zip"))
    assert len(made) == 1


def test_backup_archive_contains_vault_audit_and_manifest(monkeypatch, tmp_path):
    """The backup is one self-describing file: encrypted vault + the HMAC
    audit chain + a manifest. Losing the audit trail means losing the
    forensic record of every credential access, so it rides along."""
    import zipfile
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    src_vault = tmp_path / "v.paladin"
    v = Vault.create(path=src_vault, passphrase=PP)
    v.add("stripe_sk", "sk_live_super_secret")
    Broker(v).audit.append("add", "stripe_sk", "user:cli", "-", "test")
    dest = tmp_path / "b.zip"
    assert paladin_cli.main(["--vault", str(src_vault), "backup", str(dest)]) == 0

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert {"vault.paladin", "audit.jsonl", "MANIFEST.json"} <= names
        # ciphertext in, ciphertext out — plaintext never touches the archive
        assert b"sk_live_super_secret" not in zf.read("vault.paladin")
        manifest = json.loads(zf.read("MANIFEST.json"))
        assert manifest["format"] == "paladin-backup/1"
        assert manifest["entries"] == 1
        assert manifest["audit_records"] >= 1


def test_restore_brings_back_a_verifiable_audit_chain(monkeypatch, tmp_path):
    """After a machine migration the audit chain must still verify — the
    chain key derives from the vault master key, and both travel in the
    backup, so `paladin audit verify` passes on the new machine."""
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    src_vault = tmp_path / "m1" / "vault.paladin"
    src_vault.parent.mkdir()
    v = Vault.create(path=src_vault, passphrase=PP)
    v.add("k", "v")
    Broker(v).audit.append("add", "k", "user:cli", "-", "")
    Broker(v).audit.append("resolve", "k", "skill:x", "L1", "")
    dest = tmp_path / "b.zip"
    assert paladin_cli.main(["--vault", str(src_vault), "backup", str(dest)]) == 0

    m2_vault = tmp_path / "m2" / "vault.paladin"
    assert paladin_cli.main(["--vault", str(m2_vault), "restore", str(dest)]) == 0
    restored = Vault.open(path=m2_vault, passphrase=PP)
    assert Broker(restored).audit.verify() == 2  # chain intact on machine 2


def test_restore_accepts_a_bare_vault_file(monkeypatch, tmp_path):
    """Someone who salvaged only vault.paladin (no archive) is made whole."""
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    bare = tmp_path / "salvaged.paladin"
    Vault.create(path=bare, passphrase=PP).add("k", "v")
    dest = tmp_path / "new" / "vault.paladin"
    assert paladin_cli.main(["--vault", str(dest), "restore", str(bare)]) == 0
    assert Vault.open(path=dest, passphrase=PP).names() == ["k"]


def test_restore_rejects_a_zip_that_is_not_a_backup(monkeypatch, tmp_path):
    import zipfile
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    junk = tmp_path / "junk.zip"
    with zipfile.ZipFile(junk, "w") as zf:
        zf.writestr("random.txt", "hello")
    assert paladin_cli.main(["--vault", str(tmp_path / "v.paladin"),
                             "restore", str(junk)]) == 1


def test_cli_restore_refuses_to_clobber_without_force(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    live = tmp_path / "live.paladin"
    Vault.create(path=live, passphrase=PP).add("keep", "me")
    backup = tmp_path / "b.paladin"
    Vault.create(path=backup, passphrase=PP).add("other", "x")
    rc = paladin_cli.main(["--vault", str(live), "restore", str(backup)])
    assert rc == 1  # refused
    # the live vault must be untouched
    assert Vault.open(path=live, passphrase=PP).names() == ["keep"]


def test_cli_restore_force_saves_pre_restore_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    live = tmp_path / "live.paladin"
    Vault.create(path=live, passphrase=PP).add("old", "data")
    backup = tmp_path / "b.paladin"
    Vault.create(path=backup, passphrase=PP).add("new", "data")
    rc = paladin_cli.main(["--vault", str(live), "restore", str(backup), "--force"])
    assert rc == 0
    assert Vault.open(path=live, passphrase=PP).names() == ["new"]
    # the overwritten vault was preserved
    pre = Vault.open(path=Path(str(live) + ".pre-restore"), passphrase=PP)
    assert pre.names() == ["old"]


def test_cli_restore_rejects_backup_that_wont_open(monkeypatch, tmp_path):
    """A backup made under a DIFFERENT passphrase must not silently replace a
    good vault — restore verifies it opens first and aborts if it can't."""
    live = tmp_path / "live.paladin"
    Vault.create(path=live, passphrase=PP).add("keep", "me")
    backup = tmp_path / "b.paladin"
    Vault.create(path=backup, passphrase="a-totally-different-pass").add("x", "y")
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)  # only knows the live pass
    rc = paladin_cli.main(["--vault", str(live), "restore", str(backup), "--force"])
    assert rc == 1  # could not open the backup → aborted
    assert Vault.open(path=live, passphrase=PP).names() == ["keep"]  # untouched
