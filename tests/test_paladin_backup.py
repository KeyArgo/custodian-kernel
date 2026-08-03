"""Tests for paladin.backup -- create_backup/read_backup/restore_backup.

No test coverage existed for this module before this session's adversarial
review found a real bug in it (see test_restore_does_not_clobber_a_prior_
pre_restore_safety_copy below).
"""
from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from paladin import backup
from paladin.errors import PaladinError
from paladin.vault import Vault

PP = "correct horse battery staple"


def _vault_with_secret(path: Path, name: str, value: str) -> Vault:
    v = Vault.create(path=path, passphrase=PP)
    v.add(name, value)
    return v


def test_create_and_restore_roundtrip(tmp_path):
    vault_path = tmp_path / "home" / "vault.paladin"
    v = _vault_with_secret(vault_path, "k1", "secret-value-1")
    v.close()

    dest = tmp_path / "backup.zip"
    v2 = Vault.open(path=vault_path, passphrase=PP)
    info = backup.create_backup(v2, dest)
    v2.close()
    assert info.entry_count == 1
    assert dest.exists()
    # v2 seals the entire archive: neither secret nor value-free operational
    # metadata should be visible to somebody holding only the backup file.
    raw = dest.read_bytes()
    assert b"secret-value-1" not in raw and b"k1" not in raw
    assert not zipfile.is_zipfile(dest)

    new_home = tmp_path / "restored"
    new_vault_path = new_home / "vault.paladin"
    backup.restore_backup(dest, new_vault_path, passphrase=PP)

    restored = Vault.open(path=new_vault_path, passphrase=PP)
    try:
        assert restored._resolve_value("k1") == "secret-value-1"
    finally:
        restored.close()


def test_restore_refuses_to_overwrite_without_force(tmp_path):
    vault_path = tmp_path / "home" / "vault.paladin"
    v = _vault_with_secret(vault_path, "k1", "secret-value-1")
    dest = tmp_path / "backup.zip"
    backup.create_backup(v, dest)
    v.close()

    with pytest.raises(PaladinError, match="already exists"):
        backup.restore_backup(dest, vault_path, passphrase=PP, force=False)


def test_restore_saves_a_pre_restore_safety_copy(tmp_path):
    vault_path = tmp_path / "home" / "vault.paladin"
    v = _vault_with_secret(vault_path, "k1", "original")
    dest = tmp_path / "backup.zip"
    backup.create_backup(v, dest)
    v.close()

    # A different vault now sits at vault_path -- restoring must save it,
    # not just discard it.
    vault_path.unlink()
    replacement = Vault.create(path=vault_path, passphrase=PP)
    replacement.add("k2", "current-before-restore")
    replacement.close()

    backup.restore_backup(dest, vault_path, passphrase=PP, force=True)

    safety_path = Path(str(vault_path) + ".pre-restore")
    assert safety_path.exists()
    saved = Vault.open(path=safety_path, passphrase=PP)
    try:
        assert saved._resolve_value("k2") == "current-before-restore"
    finally:
        saved.close()


def test_restore_does_not_clobber_a_prior_pre_restore_safety_copy(tmp_path):
    """os.replace() onto a fixed `<name>.pre-restore` path silently
    overwrote it if one already existed -- two ordinary, consecutive
    restores (restore backup A, then later restore backup B instead)
    meant the second restore's safety copy clobbered the first restore's,
    permanently losing whatever "current vault before restore #1" data it
    held, with zero warning. Violated this module's own documented
    invariant: "a restore can never lose data, even a botched one."
    Found in review."""
    vault_path = tmp_path / "home" / "vault.paladin"

    # Vault A, backed up.
    vault_a = _vault_with_secret(vault_path, "k", "vault-A-value")
    backup_a = tmp_path / "backup-a.zip"
    backup.create_backup(vault_a, backup_a)
    vault_a.close()

    # Vault B replaces "current". First restore (of A) saves B as .pre-restore.
    vault_path.unlink()
    vault_b = Vault.create(path=vault_path, passphrase=PP)
    vault_b.add("k", "vault-B-value")
    vault_b.close()
    backup.restore_backup(backup_a, vault_path, passphrase=PP, force=True)

    safety_path = Path(str(vault_path) + ".pre-restore")
    saved = Vault.open(path=safety_path, passphrase=PP)
    try:
        assert saved._resolve_value("k") == "vault-B-value"
    finally:
        saved.close()

    # Vault C replaces "current" again. Second restore (of A again) must
    # NOT overwrite vault B's saved safety copy.
    vault_path.unlink()
    vault_c = Vault.create(path=vault_path, passphrase=PP)
    vault_c.add("k", "vault-C-value")
    vault_c.close()
    backup.restore_backup(backup_a, vault_path, passphrase=PP, force=True)

    # Vault B's safety copy must still exist, untouched.
    saved_b = Vault.open(path=safety_path, passphrase=PP)
    try:
        assert saved_b._resolve_value("k") == "vault-B-value"
    finally:
        saved_b.close()

    # Vault C's safety copy must exist under a DIFFERENT name.
    second_safety = Path(str(vault_path) + ".pre-restore.1")
    assert second_safety.exists()
    saved_c = Vault.open(path=second_safety, passphrase=PP)
    try:
        assert saved_c._resolve_value("k") == "vault-C-value"
    finally:
        saved_c.close()


def test_restore_rejects_a_backup_that_fails_to_decrypt(tmp_path):
    vault_path = tmp_path / "home" / "vault.paladin"
    v = _vault_with_secret(vault_path, "k1", "secret")
    dest = tmp_path / "backup.zip"
    backup.create_backup(v, dest)
    v.close()

    with pytest.raises(Exception):
        backup.restore_backup(dest, tmp_path / "elsewhere" / "vault.paladin",
                              passphrase="wrong passphrase entirely")


def test_restore_from_bare_vault_file_also_works(tmp_path):
    """Someone who only salvaged the vault file itself (no backup archive)
    is still made whole -- restore accepts a bare *.paladin file too."""
    vault_path = tmp_path / "home" / "vault.paladin"
    v = _vault_with_secret(vault_path, "k1", "bare-file-value")
    v.close()

    new_vault_path = tmp_path / "restored" / "vault.paladin"
    backup.restore_backup(vault_path, new_vault_path, passphrase=PP)

    restored = Vault.open(path=new_vault_path, passphrase=PP)
    try:
        assert restored._resolve_value("k1") == "bare-file-value"
    finally:
        restored.close()


def test_restore_legacy_zip_backup_remains_supported(tmp_path):
    vault_path = tmp_path / "home" / "vault.paladin"
    vault = _vault_with_secret(vault_path, "k1", "legacy-value")
    vault.close()
    legacy = tmp_path / "legacy.zip"
    with zipfile.ZipFile(legacy, "w") as archive:
        archive.write(vault_path, "vault.paladin")

    new_vault_path = tmp_path / "restored" / "vault.paladin"
    backup.restore_backup(legacy, new_vault_path, passphrase=PP)
    restored = Vault.open(path=new_vault_path, passphrase=PP)
    try:
        assert restored._resolve_value("k1") == "legacy-value"
    finally:
        restored.close()
