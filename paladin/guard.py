"""Value-free Paladin integrity guard for credential operations."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import zipfile
from pathlib import Path

from typing import Optional

from paladin.audit import AuditLog
from paladin.errors import PaladinError
from paladin.grants import OWNER_REQUESTERS


class IntegrityGuardError(PaladinError):
    """Audit integrity is failed; agent credential authority is suspended."""


@dataclass(frozen=True)
class IntegrityStatus:
    healthy: bool
    valid_records: int
    problem: str = ""
    audit_sha256: str = ""


class PaladinGuard:
    """Verify audit evidence before an AI receives credential authority.

    Human owners retain a recovery path; non-owner requesters fail closed.
    This guard never resolves or displays a secret value.
    """
    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    def status(self) -> IntegrityStatus:
        try:
            digest = (hashlib.sha256(self.audit.path.read_bytes()).hexdigest()
                      if self.audit.path.exists() else "")
            return IntegrityStatus(True, self.audit.verify(), audit_sha256=digest)
        except Exception as exc:
            # Audit errors are intentionally summarized; records themselves
            # remain inspectable through the value-free audit command.
            match = re.search(r"record (\d+)", str(exc))
            return IntegrityStatus(False, int(match.group(1)) if match else 0,
                                   str(exc), "")

    def backup_audit_hashes(self, directory: str | Path,
                            passphrase: Optional[str] = None,
                            keyfile: Optional[Path] = None) -> list[tuple[str, str]]:
        """Return value-free audit hashes from Paladin backup archives.

        Reads both legacy ``*.zip`` backups (v1, plaintext audit) and
        sealed ``*.paladin-backup`` archives (v2, AEAD-encrypted vault +
        audit).  For sealed backups the caller must supply the vault
        passphrase or keyfile — the guard never prompts interactively.

        The returned hashes are SHA-256 of each backup's audit content
        only (no secret values are ever extracted or exposed).
        """
        found: list[tuple[str, str]] = []
        dir_path = Path(directory).expanduser()

        # Legacy ZIP (v1) backups — audit is plaintext inside the archive.
        for archive in sorted(dir_path.glob("*.zip")):
            try:
                with zipfile.ZipFile(archive) as bundle:
                    with bundle.open("audit.jsonl") as stream:
                        digest = hashlib.sha256(stream.read()).hexdigest()
                found.append((archive.name, digest))
            except (OSError, KeyError, zipfile.BadZipFile):
                continue

        # Sealed (v2 / paladin-backup) archives — AEAD container; the
        # caller must provide credentials.  The vault blob is discarded
        # after audit extraction — no secret value is ever materialized
        # outside the backup module.
        for archive in sorted(dir_path.glob("*.paladin-backup")):
            try:
                from paladin.backup import read_backup
                blob, audit_bytes = read_backup(
                    archive, passphrase=passphrase, keyfile=keyfile,
                )
                if audit_bytes:
                    digest = hashlib.sha256(audit_bytes).hexdigest()
                else:
                    digest = "(no audit)"
                found.append((archive.name, digest))
            except Exception:
                found.append((archive.name, "(locked — passphrase/keyfile required)"))
        return found

    def require_agent_safe(self, requester: str) -> None:
        if requester in OWNER_REQUESTERS:
            return
        status = self.status()
        if not status.healthy:
            raise IntegrityGuardError(
                "Paladin Guard blocked credential authority: audit integrity failed; "
                "operator recovery is required")
