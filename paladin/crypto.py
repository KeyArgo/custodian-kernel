"""Vault cryptography: scrypt KDF + AES-256-GCM.

Design notes
------------
* One key per vault, derived from either a passphrase (scrypt, N=2**17,
  r=8, p=1 — ~128MB memory cost, still well under a second) or a raw
  32-byte keyfile. Bumped from the original 2**15 in review: 2**15 is
  fine for an interactive login screen but this key protects a
  credential vault against offline brute-force of a stolen file
  indefinitely, which calls for a higher work factor. KDF params are
  stored per-vault in the header, so this only affects newly created
  vaults — existing ones keep working with whatever N they were made
  with until rotated.
* The whole entry table is encrypted as a single blob, so at rest the
  vault leaks nothing — not entry names, not counts beyond ciphertext
  size, not metadata.
* AES-GCM gives authenticated encryption: any bit flip in the file
  fails decryption outright (surfaced as VaultLockedError), so tamper
  detection is inherent rather than bolted on.
* A fresh 12-byte nonce is drawn from ``os.urandom`` on every write.
  Keys are never reused across vaults (new random salt per vault).
* The vault header (magic, version, KDF params, salt) is bound into the
  ciphertext as GCM associated data — swapping headers between vaults
  or downgrading KDF params breaks authentication.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass

from paladin.errors import CryptoUnavailableError, VaultCorruptError, VaultLockedError

try:  # pragma: no cover - import guard exercised only without the extra
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAVE_CRYPTO = True
except ImportError:  # pragma: no cover
    AESGCM = None
    _HAVE_CRYPTO = False

MAGIC = b"PALADIN1\n"

# The pre-rename format magic. This is NOT an identifier -- it is a file-format
# version string baked into the first bytes of every vault ever written, and it
# is bound as AEAD associated data in encrypt_blob/decrypt_blob below. Rewriting
# it (as a blind rename did once) does not merely fail the magic sniff: it
# changes the AAD, so the AEAD tag no longer authenticates and every existing
# vault becomes permanently undecryptable. The plaintext is fine; only the
# literal is wrong, and the operator is told their healthy file is corrupt.
#
# Read both, write MAGIC. A legacy vault therefore opens, and upgrades to the
# current format the next time it is saved.
LEGACY_MAGIC = b"WARDEN1\n"
MAGICS = (MAGIC, LEGACY_MAGIC)
KEY_LEN = 32
NONCE_LEN = 12
SALT_LEN = 16

# scrypt parameters. N=2**17 (~128MB, well under a second on modern
# hardware) — high enough to make offline brute-force of a stolen vault
# file expensive, since unlike a login screen this key protects
# long-lived credentials, not a single session.
SCRYPT_N = 2 ** 17
SCRYPT_R = 8
SCRYPT_P = 1


def require_crypto() -> None:
    if not _HAVE_CRYPTO:
        raise CryptoUnavailableError(
            "the 'cryptography' package is required for vault encryption — "
            "install with: pip install custodian-kernel[paladin]"
        )


@dataclass(frozen=True)
class KdfParams:
    salt: bytes
    n: int = SCRYPT_N
    r: int = SCRYPT_R
    p: int = SCRYPT_P

    def to_header(self) -> dict:
        return {"kdf": "scrypt", "salt": self.salt.hex(), "n": self.n, "r": self.r, "p": self.p}

    @classmethod
    def fresh(cls) -> "KdfParams":
        return cls(salt=os.urandom(SALT_LEN))

    @classmethod
    def from_header(cls, header: dict) -> "KdfParams":
        try:
            if header["kdf"] != "scrypt":
                raise VaultCorruptError(f"unsupported KDF {header['kdf']!r}")
            return cls(salt=bytes.fromhex(header["salt"]),
                       n=int(header["n"]), r=int(header["r"]), p=int(header["p"]))
        except (KeyError, ValueError) as e:
            raise VaultCorruptError("vault header is malformed") from e


def derive_key(passphrase: str, params: KdfParams) -> bytes:
    """Derive the vault key from a passphrase."""
    if not passphrase:
        raise VaultLockedError("empty passphrase")
    # scrypt's own memory requirement is 128*N*r bytes — with the current
    # SCRYPT_N that's exactly 128MiB, so maxmem must have headroom above
    # it (some implementations reject an exact boundary as "exceeded").
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=params.salt, n=params.n, r=params.r, p=params.p,
        maxmem=192 * 1024 * 1024, dklen=KEY_LEN,
    )


def subkey(master_key: bytes, purpose: bytes) -> bytes:
    """Derive a purpose-bound subkey (e.g. the audit HMAC key) so the
    vault key itself is never used in more than one construction."""
    # This prefix is a cryptographic domain separator, not a name. It is an
    # input to every audit-chain HMAC and receipt signature ever produced, and
    # nothing renders it to a user. Renaming it buys exactly nothing and makes
    # `paladin audit verify` report tampering on untampered chains and
    # verify_signed() reject every genuine pre-rename receipt. It stays as-is.
    return hmac.new(master_key, b"warden-subkey:" + purpose, hashlib.sha256).digest()


def encrypt_blob(key: bytes, plaintext: bytes, header: dict) -> bytes:
    """Encrypt `plaintext` into the on-disk vault format.

    Layout: MAGIC + json(header) + b"\\n" + nonce + ciphertext.
    The header bytes are GCM associated data.
    """
    require_crypto()
    header_bytes = json.dumps(header, sort_keys=True).encode("utf-8")
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, MAGIC + header_bytes)
    return MAGIC + header_bytes + b"\n" + nonce + ct


def decrypt_blob(key: bytes, blob: bytes) -> bytes:
    """Reverse of encrypt_blob. Raises VaultLockedError on a wrong key
    or any tampering (GCM authentication failure)."""
    require_crypto()
    magic, header, nonce, ct = split_blob(blob)
    header_bytes = json.dumps(header, sort_keys=True).encode("utf-8")
    try:
        # AAD is the magic THIS FILE was written with, never the module
        # constant -- a legacy vault authenticates under LEGACY_MAGIC.
        return AESGCM(key).decrypt(nonce, ct, magic + header_bytes)
    except Exception as e:  # InvalidTag — deliberately not distinguished further
        raise VaultLockedError(
            "vault failed to unlock: wrong passphrase/keyfile, or the file was tampered with"
        ) from e


def split_blob(blob: bytes) -> tuple[bytes, dict, bytes, bytes]:
    """Parse the on-disk format into (magic, header, nonce, ciphertext).

    The magic is returned because it is AEAD associated data: the caller must
    authenticate against the one the file actually carries."""
    for magic in MAGICS:
        if blob.startswith(magic):
            break
    else:
        raise VaultCorruptError("not a Paladin vault (bad magic)")
    rest = blob[len(magic):]
    sep = rest.find(b"\n")
    if sep < 0 or len(rest) < sep + 1 + NONCE_LEN + 16:
        raise VaultCorruptError("vault file is truncated")
    try:
        header = json.loads(rest[:sep].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise VaultCorruptError("vault header is not valid JSON") from e
    body = rest[sep + 1:]
    return magic, header, body[:NONCE_LEN], body[NONCE_LEN:]


def wipe(buf: bytearray) -> None:
    """Best-effort zeroization of a mutable buffer. CPython gives no
    hard guarantee (the bytes may have been copied), but zeroing the
    buffers we control shrinks the window where plaintext sits in RAM."""
    for i in range(len(buf)):
        buf[i] = 0
