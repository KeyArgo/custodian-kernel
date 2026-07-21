"""Backup and restore for a paladin home — vault + audit chain, one file.

A backup is a single ``.zip`` archive containing:

* ``vault.paladin`` — the encrypted vault, byte-for-byte. It never leaves
  ciphertext: an attacker with the backup learns exactly what an attacker
  with the vault file learns (its size), no more.
* ``audit.jsonl`` — the HMAC-hash-chained audit log, if one exists. Audit
  records are value-free (event/ref/requester metadata, never secret
  values), and losing them means losing the forensic trail of every
  credential access — so a real backup carries them.
* ``MANIFEST.json`` — format version, creation time, entry count. Enough
  to sanity-check a restore; nothing identifying in it.

What a backup deliberately does NOT contain: keyfiles. A keyfile is the
key; archiving it next to the ciphertext it opens would turn "encrypted
backup" into "plaintext with extra steps". Keyfile users must back up
their keyfile separately, somewhere the backup archive is not.

The vault bytes are copied under the same exclusive lock ``Vault.save``
takes (see :func:`paladin.vault.copy_encrypted`'s locking), so a backup
can never capture a half-written vault racing a concurrent write.

Restore accepts either a backup archive or a bare ``*.paladin`` vault
file (someone who only salvaged the vault file itself is still made
whole). It verifies the backup decrypts BEFORE touching the destination,
and when overwriting, the current files are saved to ``*.pre-restore``
first — a restore can never lose data, even a botched one.
"""
from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from paladin import crypto
from paladin.errors import PaladinError, VaultMissingError
from paladin.vault import (
    VAULT_FILENAME,
    Vault,
    _harden_permissions,
    _lock_exclusive,
    _lock_release,
)

AUDIT_FILENAME = "audit.jsonl"  # kept in sync with paladin.broker.AUDIT_FILENAME
MANIFEST_FILENAME = "MANIFEST.json"
BACKUP_FORMAT = "paladin-backup/1"
BACKUP_PREFIX = "paladin-backup-"
DEFAULT_BACKUP_DIR = "~/paladin-backups"


@dataclass
class BackupInfo:
    """What a backup or restore touched — for the CLI to narrate."""

    path: Path
    entry_count: int
    has_audit: bool
    audit_records: int = 0


def _read_vault_bytes_locked(vault_path: Path) -> bytes:
    """Read the encrypted vault under the save() lock and validate the blob."""
    lock_path = vault_path.with_suffix(".lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_exclusive(lock_fd)
        blob = vault_path.read_bytes()
    finally:
        _lock_release(lock_fd)
        os.close(lock_fd)
    # Refuse to archive a torn/empty/non-vault file — a backup that cannot
    # restore is worse than no backup, because it feels like one.
    crypto.split_blob(blob)
    return blob


def default_backup_dest() -> Path:
    return Path(DEFAULT_BACKUP_DIR).expanduser()


def resolve_backup_path(dest: Optional[str]) -> Path:
    """Turn the CLI's dest argument into a concrete archive path.

    No dest → ``~/paladin-backups/paladin-backup-<ts>.zip``. A directory →
    a timestamped archive inside it. A file path → used as given.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    name = f"{BACKUP_PREFIX}{stamp}.zip"
    if dest is None:
        return default_backup_dest() / name
    p = Path(dest).expanduser()
    if p.is_dir():
        return p / name
    return p


def create_backup(vault: Vault, dest: Path) -> BackupInfo:
    """Write a backup archive of ``vault`` (already opened → passphrase is
    proven to work, so the archive is proven restorable) and its audit log.

    ``vault`` must be an OPEN vault: opening it is the passphrase check, and
    doing it in the caller keeps prompting out of this module.
    """
    dest = Path(dest)
    if dest.exists():
        raise PaladinError(f"{dest} already exists — choose another path or pass --force")

    blob = _read_vault_bytes_locked(vault.path)
    audit_path = vault.path.parent / AUDIT_FILENAME
    audit_bytes = audit_path.read_bytes() if audit_path.exists() else None
    audit_records = (
        sum(1 for line in audit_bytes.splitlines() if line.strip())
        if audit_bytes is not None else 0
    )

    manifest = {
        "format": BACKUP_FORMAT,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "entries": len(vault.names()),
        "audit_records": audit_records,
    }

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        # The vault blob is already AES-256-GCM ciphertext — compressing it
        # gains nothing (and a compressed-size oracle helps nobody). STORED
        # keeps the archive dead simple; the audit log is plain JSONL and
        # small, so it is not worth a mixed-compression scheme either.
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest, indent=2))
            zf.writestr(VAULT_FILENAME, blob)
            if audit_bytes is not None:
                zf.writestr(AUDIT_FILENAME, audit_bytes)
        os.replace(tmp, dest)
        _harden_permissions(dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return BackupInfo(path=dest, entry_count=manifest["entries"],
                      has_audit=audit_bytes is not None,
                      audit_records=audit_records)


def read_backup(source: Path) -> tuple[bytes, Optional[bytes]]:
    """Return ``(vault_blob, audit_bytes_or_None)`` from a backup source.

    Accepts a backup archive or a bare vault file. Every returned blob is
    validated as a well-formed AEAD container before anything downstream
    runs, so a corrupt or wrong file fails here, loudly, with its name.
    """
    source = Path(source)
    if not source.exists():
        raise VaultMissingError(f"no backup file at {source}")
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as zf:
            names = set(zf.namelist())
            if VAULT_FILENAME not in names:
                raise PaladinError(
                    f"{source} is a zip but not a paladin backup "
                    f"(no {VAULT_FILENAME} inside)")
            blob = zf.read(VAULT_FILENAME)
            audit = zf.read(AUDIT_FILENAME) if AUDIT_FILENAME in names else None
    else:
        blob = source.read_bytes()
        audit = None
    crypto.split_blob(blob)
    return blob, audit


def _next_safety_path(live: Path) -> Path:
    """Return a `.pre-restore` path that doesn't already exist yet.

    os.replace() onto a fixed `<name>.pre-restore` path silently overwrites
    it if one already exists -- two ordinary, consecutive restores (restore
    backup A, later restore backup B instead; or just retry) meant the
    second restore's safety copy clobbered the first restore's, permanently
    losing whatever "current vault before restore #1" data it held, with
    zero warning. Violates this module's own documented invariant ("a
    restore can never lose data, even a botched one"). Found in review.
    """
    candidate = Path(str(live) + ".pre-restore")
    n = 1
    while candidate.exists():
        candidate = Path(str(live) + f".pre-restore.{n}")
        n += 1
    return candidate


def restore_backup(source: Path, vault_path: Path, *, force: bool = False,
                   passphrase: Optional[str] = None,
                   keyfile: Optional[Path] = None) -> BackupInfo:
    """Restore ``source`` into ``vault_path`` (and its sibling audit log).

    Order of operations is the whole design:

    1. Read + validate the backup, then PROVE it decrypts with the key
       material the user has now. A backup nobody can open must never
       replace a vault somebody can.
    2. Only then touch the destination — and save every file about to be
       overwritten to ``<name>.pre-restore`` first.
    """
    blob, audit = read_backup(source)

    import tempfile
    probe_fd, probe_name = tempfile.mkstemp(suffix=".paladin")
    try:
        with os.fdopen(probe_fd, "wb") as f:
            f.write(blob)
        probe = Vault.open(path=Path(probe_name), passphrase=passphrase,
                           keyfile=keyfile)
        try:
            entry_count = len(probe.names())
        finally:
            probe.close()
    finally:
        os.unlink(probe_name)

    vault_path = Path(vault_path)
    audit_path = vault_path.parent / AUDIT_FILENAME
    if vault_path.exists() and not force:
        raise PaladinError(
            f"a vault already exists at {vault_path}. Pass --force to replace "
            f"it (the current vault is first saved to {vault_path}.pre-restore).")

    vault_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(vault_path.parent, 0o700)
    for live in (vault_path, audit_path):
        if live.exists():
            safety = _next_safety_path(live)
            os.replace(live, safety)

    def _write(path: Path, data: bytes) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            _harden_permissions(path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    _write(vault_path, blob)
    audit_records = 0
    if audit is not None:
        _write(audit_path, audit)
        audit_records = sum(1 for line in audit.splitlines() if line.strip())
    return BackupInfo(path=vault_path, entry_count=entry_count,
                      has_audit=audit is not None, audit_records=audit_records)
