"""The encrypted vault: entries, metadata, and grants in one AEAD blob.

At rest the vault is a single AES-256-GCM ciphertext — names, values,
metadata, and the grant table are all inside it. An attacker with the
file learns only its size. Writes are atomic (tmp file + rename in the
same directory) and permission-hardened (0700 dir, 0600 file).

The vault is the *human's* API surface. Agents never touch this class;
they go through :class:`caduceus.broker.Broker`, which enforces grants
and audits every access.
"""
from __future__ import annotations

import getpass
import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from caduceus import crypto
from caduceus.errors import (
    UnknownRefError,
    VaultCorruptError,
    VaultLockedError,
    VaultMissingError,
    CaduceusError,
)
from caduceus.refs import SecretRef, valid_name

DEFAULT_VAULT_DIR = Path(os.environ.get("CADUCEUS_HOME", "~/.caduceus")).expanduser()
VAULT_FILENAME = "vault.caduceus"
PASSPHRASE_ENV = "CADUCEUS_PASSPHRASE"
KEYFILE_ENV = "CADUCEUS_KEYFILE"


@dataclass
class Entry:
    """One secret: value + metadata. Only ever exists decrypted in RAM."""

    name: str
    value: str
    kind: str = "secret"          # secret | env | token | password
    profile: str = "default"      # env-manager grouping (dev/staging/prod/...)
    env_var: Optional[str] = None  # default env var name at injection time
    note: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    rotations: int = 0

    def meta(self) -> dict:
        """Everything about the entry EXCEPT the value — safe to show."""
        return {
            "name": self.name,
            "kind": self.kind,
            "profile": self.profile,
            "env_var": self.env_var,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rotations": self.rotations,
            "length": len(self.value),
        }


def _load_key_material(passphrase: Optional[str], keyfile: Optional[Path],
                       params: crypto.KdfParams) -> bytes:
    if keyfile is not None:
        raw = Path(keyfile).read_bytes()
        if len(raw) != crypto.KEY_LEN:
            raise VaultLockedError("keyfile must be exactly 32 raw bytes")
        return raw
    if passphrase is None:
        raise VaultLockedError("no passphrase or keyfile provided")
    return crypto.derive_key(passphrase, params)


def _harden_permissions(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


class Vault:
    """An unlocked vault. Construct via :meth:`create` or :meth:`open`."""

    def __init__(self, path: Path, key: bytes, params: crypto.KdfParams,
                 entries: dict[str, Entry], grants: list[dict]):
        self.path = Path(path)
        self._key = key
        self._params = params
        self._entries = entries
        self._grants = grants  # raw grant dicts; wrapped by GrantPolicy

    # -- lifecycle -----------------------------------------------------------

    @classmethod
    def default_path(cls) -> Path:
        return DEFAULT_VAULT_DIR / VAULT_FILENAME

    @classmethod
    def create(cls, path: Optional[Path] = None, passphrase: Optional[str] = None,
               keyfile: Optional[Path] = None) -> "Vault":
        path = Path(path) if path else cls.default_path()
        if path.exists():
            raise CaduceusError(f"a vault already exists at {path}")
        crypto.require_crypto()
        params = crypto.KdfParams.fresh()
        key = _load_key_material(passphrase, keyfile, params)
        vault = cls(path, key, params, entries={}, grants=[])
        vault.save()
        return vault

    @classmethod
    def open(cls, path: Optional[Path] = None, passphrase: Optional[str] = None,
             keyfile: Optional[Path] = None) -> "Vault":
        path = Path(path) if path else cls.default_path()
        if not path.exists():
            raise VaultMissingError(f"no vault at {path} — run `caduceus init` first")
        blob = path.read_bytes()
        header, _, _ = crypto.split_blob(blob)
        params = crypto.KdfParams.from_header(header)
        key = _load_key_material(passphrase, keyfile, params)
        plaintext = crypto.decrypt_blob(key, blob)
        try:
            doc = json.loads(plaintext.decode("utf-8"))
            entries = {name: Entry(**e) for name, e in doc.get("entries", {}).items()}
            grants = list(doc.get("grants", []))
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
            raise VaultCorruptError("vault decrypted but payload is malformed") from e
        return cls(path, key, params, entries, grants)

    @classmethod
    def open_from_env(cls, path: Optional[Path] = None,
                      interactive: bool = False) -> "Vault":
        """Unlock using CADUCEUS_KEYFILE / CADUCEUS_PASSPHRASE, optionally
        falling back to an interactive prompt (CLI use only)."""
        keyfile = os.environ.get(KEYFILE_ENV)
        passphrase = os.environ.get(PASSPHRASE_ENV)
        if keyfile:
            return cls.open(path, keyfile=Path(keyfile))
        if passphrase is None and interactive:
            passphrase = getpass.getpass("vault passphrase: ")
        return cls.open(path, passphrase=passphrase)

    def save(self) -> None:
        """Atomic, permission-hardened write of the encrypted vault."""
        doc = {
            "entries": {name: vars(e) for name, e in self._entries.items()},
            "grants": self._grants,
        }
        blob = crypto.encrypt_blob(
            self._key, json.dumps(doc).encode("utf-8"),
            self._params.to_header(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
            _harden_permissions(self.path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def rotate_master(self, new_passphrase: Optional[str] = None,
                      new_keyfile: Optional[Path] = None) -> None:
        """Re-encrypt the vault under a new master key (new salt too)."""
        params = crypto.KdfParams.fresh()
        self._key = _load_key_material(new_passphrase, new_keyfile, params)
        self._params = params
        self.save()

    def audit_key(self) -> bytes:
        """Purpose-bound subkey for the audit log's HMAC chain."""
        return crypto.subkey(self._key, b"audit")

    # -- entry management (human/CLI surface) --------------------------------

    def add(self, name: str, value: str, kind: str = "secret", profile: str = "default",
            env_var: Optional[str] = None, note: str = "", overwrite: bool = False) -> SecretRef:
        if not valid_name(name):
            raise CaduceusError(f"invalid secret name {name!r}")
        if name in self._entries and not overwrite:
            raise CaduceusError(f"entry {name!r} already exists (use overwrite/edit)")
        prior = self._entries.get(name)
        entry = Entry(name=name, value=value, kind=kind, profile=profile,
                      env_var=env_var or _default_env_var(name), note=note)
        if prior is not None:
            entry.created_at = prior.created_at
            entry.rotations = prior.rotations + 1
        self._entries[name] = entry
        self.save()
        return SecretRef(name)

    def update_meta(self, name: str, profile: Optional[str] = None,
                    env_var: Optional[str] = None, note: Optional[str] = None) -> None:
        entry = self._require(name)
        if profile is not None:
            entry.profile = profile
        if env_var is not None:
            entry.env_var = env_var
        if note is not None:
            entry.note = note
        entry.updated_at = time.time()
        self.save()

    def delete(self, name: str) -> None:
        self._require(name)
        del self._entries[name]
        self.save()

    def names(self, profile: Optional[str] = None) -> list[str]:
        return sorted(
            n for n, e in self._entries.items()
            if profile is None or e.profile == profile
        )

    def meta(self, name: str) -> dict:
        return self._require(name).meta()

    def iter_meta(self, profile: Optional[str] = None) -> Iterator[dict]:
        for name in self.names(profile):
            yield self._entries[name].meta()

    def import_env_file(self, env_path: Path, profile: str = "default",
                        overwrite: bool = False) -> list[str]:
        """Import KEY=value lines from a .env file. Returns imported names.
        The plaintext .env file should be shredded by the caller afterward —
        the CLI prints a reminder."""
        imported = []
        for line in Path(env_path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if not key or not value:
                continue
            name = key.lower()
            self.add(name, value, kind="env", profile=profile,
                     env_var=key, overwrite=overwrite)
            imported.append(name)
        return imported

    # -- value access (broker-only surface) ----------------------------------

    def _resolve_value(self, name: str) -> str:
        """Return the plaintext value. Package-private on purpose: the only
        legitimate caller is Broker, which enforces grants + audit. Nothing
        in the CLI ever prints what this returns."""
        return self._require(name).value

    def _require(self, name: str) -> Entry:
        if name not in self._entries:
            raise UnknownRefError(f"no entry named {name!r} in vault")
        return self._entries[name]

    # -- grants blob (owned by GrantPolicy) ----------------------------------

    @property
    def raw_grants(self) -> list[dict]:
        return self._grants

    def set_raw_grants(self, grants: list[dict]) -> None:
        self._grants = grants
        self.save()


def _default_env_var(name: str) -> str:
    return name.replace("/", "_").replace(".", "_").replace("-", "_").upper()
