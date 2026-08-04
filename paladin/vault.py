"""The encrypted vault: entries, metadata, and grants in one AEAD blob.

At rest the vault is a single AES-256-GCM ciphertext — names, values,
metadata, and the grant table are all inside it. An attacker with the
file learns only its size. Writes are atomic (tmp file + rename in the
same directory) and permission-hardened (0700 dir, 0600 file).

The vault is the *human's* API surface. Agents never touch this class;
they go through :class:`paladin.broker.Broker`, which enforces grants
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

from paladin import crypto
from paladin.errors import (
    UnknownRefError,
    VaultCorruptError,
    VaultLockedError,
    VaultMissingError,
    PaladinError,
)
from paladin.refs import SecretRef, valid_name

HOME_ENV = "PALADIN_HOME"
VAULT_FILENAME = "vault.paladin"
PASSPHRASE_ENV = "PALADIN_PASSPHRASE"
KEYFILE_ENV = "PALADIN_KEYFILE"

# Pre-rename spellings, honored on read and never written. These are the only
# place the old name survives, and it has to: the rename cannot reach a vault
# already sitting at ~/.warden/vault.warden, nor a shell that still exports
# WARDEN_PASSPHRASE. Dropping them would not fail loudly -- the operator would
# get a fresh empty vault and a working prompt, with their real credentials
# still on disk but invisible. That is the worst available failure mode for a
# credential tool, so the old names stay until a migration command exists.
LEGACY_HOME_ENV = "WARDEN_HOME"
LEGACY_VAULT_FILENAME = "vault.warden"
LEGACY_PASSPHRASE_ENV = "WARDEN_PASSPHRASE"
LEGACY_KEYFILE_ENV = "WARDEN_KEYFILE"


def _env(name: str, legacy_name: str) -> Optional[str]:
    """Read ``name``, falling back to its pre-rename spelling.

    An empty value is still a *set* value: ``PALADIN_KEYFILE= paladin ...``
    means "explicitly none", so it must shadow the legacy variable rather
    than silently promote it."""
    value = os.environ.get(name)
    if value is not None:
        return value
    return os.environ.get(legacy_name)


def default_vault_dir() -> Path:
    """The vault home, resolved at call time.

    ``PALADIN_HOME`` wins; ``WARDEN_HOME`` is honored but deprecated. With
    neither set the default is ``~/.paladin`` -- except when that does not
    exist and a pre-rename ``~/.warden`` does, in which case the existing
    vault is used rather than shadowed by an empty new one."""
    explicit = _env(HOME_ENV, LEGACY_HOME_ENV)
    # Truthy, not `is not None`: Path("").expanduser() is Path("."), so an
    # empty PALADIN_HOME would silently put the vault in the current working
    # directory -- usually whatever repo the agent happens to be in. An empty
    # home is not a location; fall through to the default. (_env still returns
    # "" so the empty value shadows the legacy variable rather than promoting
    # it -- it just doesn't name a directory.)
    if explicit:
        return Path(explicit).expanduser()
    current = Path("~/.paladin").expanduser()
    if not current.exists() and Path("~/.warden").expanduser().exists():
        return Path("~/.warden").expanduser()
    return current


DEFAULT_VAULT_DIR = default_vault_dir()


@dataclass
class Entry:
    """One secret: value + metadata. Only ever exists decrypted in RAM."""

    name: str
    value: str
    kind: str = "secret"          # secret | env | token | password
    profile: str = "default"      # env-manager grouping (dev/staging/prod/...)
    env_var: Optional[str] = None  # default env var name at injection time
    username: Optional[str] = None  # optional login/account name; never a secret value
    note: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    rotations: int = 0
    # Hosts this secret may be sent to. Empty = unrestricted (the default,
    # so old vaults with no such key load unchanged — the dataclass default
    # fills in). When set, egress-domain-guard denies any tool call that
    # would send this secret to a host not on the list.
    allowed_hosts: list = field(default_factory=list)

    def meta(self) -> dict:
        """Everything about the entry EXCEPT the value — safe to show."""
        return {
            "name": self.name,
            "kind": self.kind,
            "profile": self.profile,
            "env_var": self.env_var,
            "username": self.username,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "rotations": self.rotations,
            "allowed_hosts": list(self.allowed_hosts),
            "length": len(self.value),
        }


def _load_key_material(passphrase: Optional[str], keyfile: Optional[Path],
                       params: crypto.KdfParams) -> bytes:
    if keyfile is not None:
        try:
            raw = Path(keyfile).read_bytes()
        except OSError as e:
            # Covers a missing file, a directory given instead of a file,
            # unreadable permissions, a broken symlink, etc. — every one of
            # these must fail as a clean VaultLockedError, not a raw
            # traceback. This is the single, shared choke point: every
            # caller that opens a vault by keyfile (open_from_env's
            # PALADIN_KEYFILE path, the CLI's --keyfile flag, direct
            # Vault.open(keyfile=...) calls) routes through here, so fixing
            # it here — once — covers all of them instead of requiring each
            # call site to duplicate the check.
            raise VaultLockedError(
                f"keyfile {str(keyfile)!r} could not be read "
                f"({type(e).__name__}: {e}). If this came from PALADIN_KEYFILE, "
                f"fix the path, regenerate the keyfile, or unset PALADIN_KEYFILE "
                f"to fall back to PALADIN_PASSPHRASE instead."
            ) from e
        if len(raw) != crypto.KEY_LEN:
            raise VaultLockedError("keyfile must be exactly 32 raw bytes")
        return raw
    if passphrase is None:
        raise VaultLockedError("no passphrase or keyfile provided")
    return crypto.derive_key(passphrase, params)


try:  # POSIX
    import fcntl

    def _lock_exclusive(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _lock_release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

except ImportError:  # Windows: no fcntl, lock a byte range instead
    import msvcrt

    def _lock_exclusive(fd: int) -> None:
        # Unlike flock's indefinite wait, LK_LOCK retries for ~10s and then
        # raises OSError. A save() racing a slower one fails loudly rather
        # than blocking; callers see the error instead of a silent clobber.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _lock_release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def _harden_permissions(path: Path) -> None:
    # NOTE: on Windows os.chmod only toggles the read-only bit — it does NOT
    # restrict other users. The 0600/0700 guarantee in this module's docstring
    # holds on POSIX only. On Windows the AEAD encryption is the sole
    # protection for vault contents at rest.
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def copy_encrypted(src: Path, dest: Path) -> Path:
    """Copy the encrypted vault file ``src`` → ``dest`` for backup/restore.

    The copy stays ciphertext end to end — no plaintext is ever written, so a
    backup is exactly as safe to store as the vault itself (an attacker with
    it learns only its size). The read holds the same exclusive ``.lock`` that
    :meth:`Vault.save` takes, so a backup can never capture a half-written
    vault racing a concurrent ``add``/``edit``. The source bytes are checked to
    be a well-formed AEAD blob before anything is written, and the write is
    atomic (tmp + rename) and permission-hardened (0600), just like save().

    This does NOT require the passphrase — copying ciphertext needs no key.
    Callers that want to prove the copy is *restorable* (i.e. the passphrase
    opens it) should ``Vault.open`` it separately; the CLI does exactly that.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.exists():
        raise VaultMissingError(f"no vault at {src} — nothing to copy")
    if dest.resolve() == src.resolve():
        raise PaladinError(f"source and destination are the same file ({src})")
    lock_path = src.with_suffix(".lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_exclusive(lock_fd)
        blob = src.read_bytes()
        # Reject an empty/torn/non-vault file loudly rather than writing a
        # useless "backup" that would fail to restore. split_blob raises on
        # anything that isn't our AEAD container.
        crypto.split_blob(blob)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(dest.parent, 0o700)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, dest)
            _harden_permissions(dest)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    finally:
        _lock_release(lock_fd)
        os.close(lock_fd)
    return dest


class Vault:
    """An unlocked vault. Construct via :meth:`create` or :meth:`open`."""

    def __init__(self, path: Path, key: bytes, params: crypto.KdfParams,
                 entries: dict[str, Entry], grants: list[dict]):
        self.path = Path(path)
        # A bytearray (not bytes) so close()/__exit__ can actually zero it —
        # bytes are immutable, there'd be nothing to wipe. See close().
        self._key = bytearray(key)
        self._params = params
        self._entries = entries
        self._grants = grants  # raw grant dicts; wrapped by GrantPolicy
        self._closed = False

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> "Vault":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        """Best-effort cleanup of secret material held in this process.

        Zeroes the master key in place (it's a bytearray specifically so
        this is possible — bytes are immutable) and drops references to
        every decrypted Entry so they become eligible for GC instead of
        sitting in RAM for the rest of the process's life. This is NOT a
        guarantee: CPython may have copied the key/values elsewhere (e.g.
        during scrypt/AESGCM calls, or if a caller holds their own
        reference to an Entry — see the module docstring's note on
        _require()), and Python's own string immutability means a
        decrypted Entry.value can't be zeroed in place at all, only
        dereferenced. Still, closing a Vault you're done with shrinks the
        window plaintext sits in RAM, which is strictly better than
        relying on non-deterministic GC alone. Found missing in review —
        crypto.wipe() existed but nothing ever called it."""
        if self._closed:
            return
        crypto.wipe(self._key)
        self._entries = {}
        self._grants = []
        self._closed = True

    @classmethod
    def default_path(cls) -> Path:
        # Resolve PALADIN_HOME at call time, not import time, so a value set
        # after import (tests, or a process that changes it) is honored.
        base = default_vault_dir()
        current = base / VAULT_FILENAME
        if not current.exists() and (base / LEGACY_VAULT_FILENAME).exists():
            return base / LEGACY_VAULT_FILENAME
        return current

    @classmethod
    def create(cls, path: Optional[Path] = None, passphrase: Optional[str] = None,
               keyfile: Optional[Path] = None) -> "Vault":
        path = Path(path) if path else cls.default_path()
        if path.exists():
            raise PaladinError(f"a vault already exists at {path}")
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
            raise VaultMissingError(f"no vault at {path} — run `paladin init` first")
        blob = path.read_bytes()
        _, header, _, _ = crypto.split_blob(blob)
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
        """Unlock using PALADIN_KEYFILE / PALADIN_PASSPHRASE, optionally
        falling back to an interactive prompt (CLI use only).

        PALADIN_KEYFILE takes priority — but when it is set AND a passphrase
        is also available, a VaultLockedError from the keyfile attempt will
        fall back to the passphrase.  This handles the common case where an
        operator has KEYFILE configured for their regular vault but is
        working with a disposable passphrase-created vault in a different
        PALADIN_HOME.  Fallback does NOT occur when the keyfile itself is
        missing or unreadable (those are configuration errors that should be
        corrected in the env), only when the keyfile was read successfully
        but the vault it unlocks is a different one.

        A PALADIN_KEYFILE that doesn't exist (or can't be read) is a
        configuration error, not a signal to quietly try the passphrase
        instead — silently falling back could unlock a *different* vault
        than the caller thinks they're using, which is worse for a
        credential tool than failing loudly. That check lives in the
        single shared choke point every keyfile-opening path already
        goes through, _load_key_material() (see its docstring) — not
        duplicated here — so a missing *vault* (VaultMissingError, "run
        `paladin init` first") is still reported first if both are wrong,
        which is the more fundamental problem for a first-time user.
        """
        keyfile = _env(KEYFILE_ENV, LEGACY_KEYFILE_ENV)
        passphrase = _env(PASSPHRASE_ENV, LEGACY_PASSPHRASE_ENV)
        if keyfile:
            try:
                return cls.open(path, keyfile=Path(keyfile))
            except VaultLockedError:
                # The keyfile was read successfully but the vault doesn't
                # unlock with it (e.g. a different vault at this path).
                # If a passphrase is also available, give it a chance.
                if passphrase:
                    return cls.open(path, passphrase=passphrase)
                raise
        if passphrase is None and interactive:
            from paladin._prompt import read_secret
            passphrase = read_secret("vault passphrase: ")
        return cls.open(path, passphrase=passphrase)

    def save(self) -> None:
        """Atomic, permission-hardened write of the encrypted vault.

        Holds an exclusive flock on a sibling ``.lock`` file for the
        duration of the write so two concurrent ``save()`` calls (e.g.
        two ``paladin`` CLI invocations racing) serialize instead of one
        silently clobbering the other's write — found missing in review.
        This narrows but doesn't eliminate the lost-update window: it
        protects the write itself, not the whole open→modify→save
        lifecycle across two separate processes (that would need a lock
        held from open() through save(), a larger change than this)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        lock_path = self.path.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            _lock_exclusive(lock_fd)
            doc = {
                "entries": {name: vars(e) for name, e in self._entries.items()},
                "grants": self._grants,
            }
            blob = crypto.encrypt_blob(
                self._key, json.dumps(doc).encode("utf-8"),
                self._params.to_header(),
            )
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
        finally:
            _lock_release(lock_fd)
            os.close(lock_fd)

    def rotate_master(self, new_passphrase: Optional[str] = None,
                      new_keyfile: Optional[Path] = None) -> None:
        """Re-encrypt the vault under a new master key (new salt too)."""
        params = crypto.KdfParams.fresh()
        new_key = _load_key_material(new_passphrase, new_keyfile, params)
        crypto.wipe(self._key)  # old key is retired; zero it before dropping
        self._key = bytearray(new_key)
        self._params = params
        self.save()

    def audit_key(self) -> bytes:
        """Purpose-bound subkey for the audit log's HMAC chain."""
        return crypto.subkey(self._key, b"audit")

    # -- entry management (human/CLI surface) --------------------------------

    def add(self, name: str, value: str, kind: str = "secret", profile: str = "default",
            env_var: Optional[str] = None, username: Optional[str] = None,
            note: str = "", overwrite: bool = False,
            allowed_hosts: Optional[list] = None) -> SecretRef:
        if not valid_name(name):
            raise PaladinError(
                f"invalid secret name {name!r}: use 1-128 letters, numbers, "
                "dots, underscores, hyphens, or slashes; spaces are not allowed. "
                "Store the account/login name separately with --username."
            )
        _validate_username(username)
        if name in self._entries and not overwrite:
            raise PaladinError(f"entry {name!r} already exists (use overwrite/edit)")
        prior = self._entries.get(name)
        entry = Entry(name=name, value=value, kind=kind, profile=profile,
                      env_var=env_var or _default_env_var(name), username=username,
                      note=note,
                      allowed_hosts=list(allowed_hosts or []))
        if prior is not None:
            entry.created_at = prior.created_at
            entry.rotations = prior.rotations + 1
            if allowed_hosts is None:
                entry.allowed_hosts = list(prior.allowed_hosts)  # preserve on re-add
        self._entries[name] = entry
        self.save()
        return SecretRef(name)

    def update_meta(self, name: str, profile: Optional[str] = None,
                    env_var: Optional[str] = None, username: Optional[str] = None,
                    note: Optional[str] = None,
                    kind: Optional[str] = None, allowed_hosts: Optional[list] = None) -> None:
        entry = self._require(name)
        if kind is not None:
            if kind not in {"secret", "env", "token", "password"}:
                raise PaladinError(f"invalid secret kind {kind!r}")
            entry.kind = kind
        if profile is not None:
            entry.profile = profile
        if env_var is not None:
            entry.env_var = env_var
        if username is not None:
            _validate_username(username)
            entry.username = username or None
        if note is not None:
            entry.note = note
        if allowed_hosts is not None:
            entry.allowed_hosts = list(allowed_hosts)
        entry.updated_at = time.time()
        self.save()

    def rotate_value(self, name: str, value: str) -> None:
        """Replace only the secret value, preserving all metadata."""
        entry = self._require(name)
        entry.value = value
        entry.rotations += 1
        entry.updated_at = time.time()
        self.save()

    def edit(self, name: str, *, new_name: Optional[str] = None,
             new_value: Optional[str] = None, rotate: bool = False,
             profile: Optional[str] = None, env_var: Optional[str] = None,
             username: Optional[str] = None, note: Optional[str] = None,
             kind: Optional[str] = None,
             allowed_hosts: Optional[list] = None) -> int:
        """Apply a complete human edit in one validated, atomic vault save.

        ``new_name`` also migrates exact-name grants. All validation happens
        before the in-memory document is changed, so a bad field cannot leave
        a renamed or rotated entry behind. Returns exact grants migrated.
        """
        entry = self._require(name)
        target = new_name or name
        if target != name:
            if not valid_name(target):
                raise PaladinError(f"invalid secret name {target!r}")
            if target in self._entries:
                raise PaladinError(f"entry {target!r} already exists")
        if kind is not None and kind not in {"secret", "env", "token", "password"}:
            raise PaladinError(f"invalid secret kind {kind!r}")
        _validate_username(username)
        if rotate and new_value is None:
            raise PaladinError("a rotated value is required")

        migrated = 0
        new_grants = self._grants
        if target != name:
            new_grants = []
            for grant in self._grants:
                copied = dict(grant)
                if copied.get("ref_pattern") == name:
                    copied["ref_pattern"] = target
                    migrated += 1
                new_grants.append(copied)

        if target != name:
            del self._entries[name]
            entry.name = target
            self._entries[target] = entry
            self._grants = new_grants
        if rotate:
            entry.value = new_value
            entry.rotations += 1
        if kind is not None:
            entry.kind = kind
        if profile is not None:
            entry.profile = profile
        if env_var is not None:
            entry.env_var = env_var
        if username is not None:
            entry.username = username or None
        if note is not None:
            entry.note = note
        if allowed_hosts is not None:
            entry.allowed_hosts = list(allowed_hosts)
        entry.updated_at = time.time()
        self.save()
        return migrated

    def rename(self, name: str, new_name: str) -> int:
        """Atomically rename an entry and migrate exact-name grants.

        Wildcard grants are intentionally not changed: their owner expressed a
        pattern policy, not an alias that should be silently rewritten.
        """
        return self.edit(name, new_name=new_name)

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


def _validate_username(username: Optional[str]) -> None:
    """Keep optional login metadata safe for terminal and JSON display."""
    if username is None:
        return
    if len(username) > 256:
        raise PaladinError("username must be 256 characters or fewer")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in username):
        raise PaladinError("username cannot contain control characters")


def _default_env_var(name: str) -> str:
    return name.replace("/", "_").replace(".", "_").replace("-", "_").upper()
