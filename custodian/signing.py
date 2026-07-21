"""Ed25519 signing for governed receipts — authenticity on top of integrity.

A ``GovernedReceipt``'s SHA-256 fingerprint is *tamper-evident*: change any
covered field and ``verify()`` fails. But a hash is not a signature — anyone
can compute a valid fingerprint over fabricated data, so integrity alone does
not prove a receipt was issued by *your* kernel.

This module adds the missing authenticity layer. The kernel holds an Ed25519
private key; each receipt's fingerprint is signed with it. A receipt can then
be verified against the kernel's *public* key, and cannot be forged by anyone
who does not hold the private key. This is the same guarantee cyberware.systems
provides with Ed25519-signed execution results.

It is intentionally additive and optional: unsigned receipts keep working
exactly as before (integrity only). Sign them when you need authenticity.

    from custodian.signing import generate_keypair, sign_receipt, verify_signed
    priv, pub = generate_keypair()
    signed = sign_receipt(receipt, priv)          # detached — receipt untouched
    assert verify_signed(signed, expected_public_key_hex=pub)  # False if forged or re-keyed

Requires the ``cryptography`` package (a base dependency of custodian-kernel).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    _HAVE_CRYPTO = True
except ImportError:  # pragma: no cover - cryptography is a base dep
    _HAVE_CRYPTO = False


class SigningUnavailableError(RuntimeError):
    """Raised when signing is requested but ``cryptography`` is not installed."""


def _require_crypto() -> None:
    if not _HAVE_CRYPTO:
        raise SigningUnavailableError(
            "receipt signing needs the 'cryptography' package: pip install custodian-kernel"
        )


def generate_keypair() -> Tuple[str, str]:
    """Return a fresh ``(private_key_hex, public_key_hex)`` Ed25519 pair.

    Store the private hex somewhere the agent cannot read (e.g. a paladin
    vault or an operator-only file); publish the public hex so anyone can
    verify receipts.
    """
    _require_crypto()
    priv = Ed25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return priv_raw.hex(), pub_raw.hex()


def public_key_for(private_key_hex: str) -> str:
    """Derive the public key hex from a private key hex."""
    _require_crypto()
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()


def sign_fingerprint(fingerprint: str, private_key_hex: str) -> str:
    """Sign a receipt fingerprint, returning the signature as hex."""
    _require_crypto()
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    return priv.sign(fingerprint.encode()).hex()


def verify_fingerprint(fingerprint: str, signature_hex: str, public_key_hex: str) -> bool:
    """True iff ``signature_hex`` is a valid signature of ``fingerprint``."""
    _require_crypto()
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        pub.verify(bytes.fromhex(signature_hex), fingerprint.encode())
        return True
    except (InvalidSignature, ValueError):
        return False


def sign_receipt(receipt, private_key_hex: str, key_id: str = "") -> dict:
    """Return a detached signed envelope for ``receipt``.

    The receipt object is not modified. The envelope carries the receipt dict,
    the signature over its fingerprint, and the public key needed to verify.

    ``key_id``, if given, is carried in the envelope alongside the public
    key -- it lets a verifier using a SigningKeyRing look up this key's
    rotation status by a stable human-readable name (e.g. "kernel-2026-07")
    instead of the raw hex. Purely additive: omit it and this behaves
    exactly as before.
    """
    _require_crypto()
    envelope = {
        "receipt": receipt.to_dict(),
        "signature": sign_fingerprint(receipt.fingerprint, private_key_hex),
        "public_key": public_key_for(private_key_hex),
        "alg": "Ed25519",
    }
    if key_id:
        envelope["key_id"] = key_id
    return envelope


def verify_signed(signed: dict, expected_public_key_hex: str) -> bool:
    """Verify a signed envelope end to end.

    Checks (1) the receipt's own fingerprint is intact, (2) the signature is
    valid for that fingerprint, and (3) that the receipt was signed by
    exactly ``expected_public_key_hex`` (so an attacker cannot re-sign
    forged data with their own key and swap in their public key). Returns
    False on any failure.

    ``expected_public_key_hex`` is required, not optional. It used to
    default to None, which skipped check (3) entirely: since the envelope
    itself carries a "public_key" field, an attacker could fabricate a
    receipt, sign it with a throwaway keypair, and embed that key in the
    envelope -- verify_signed(forged) returned True, because "verify
    against whatever key claims to have signed it" is not an authenticity
    check at all, just an internal-consistency check. There is no
    legitimate reason to call this without knowing which key you trust --
    that is the entire point of a signature. Found in review.
    """
    _require_crypto()
    from custodian.receipt import GovernedReceipt

    try:
        receipt = GovernedReceipt(**signed["receipt"])
    except (TypeError, KeyError):
        return False
    if not receipt.verify():
        return False
    public_key = signed.get("public_key", "")
    if public_key != expected_public_key_hex:
        return False
    return verify_fingerprint(receipt.fingerprint, signed.get("signature", ""), public_key)


class KeyStatus(str, Enum):
    """Where a signing key sits in its rotation lifecycle."""
    ACTIVE = "active"      # currently used for new signatures; valid to verify
    RETIRED = "retired"    # no longer signs new receipts; still valid to verify old ones
    REVOKED = "revoked"    # compromised/invalidated; rejected even for old receipts


@dataclass
class KeyRingEntry:
    key_id: str
    public_key_hex: str
    status: KeyStatus = KeyStatus.ACTIVE


class SigningKeyRing:
    """A rotation-ready registry of trusted signing keys.

    custodian/signing.py's single-key model (sign with one private key,
    verify against one hardcoded expected_public_key_hex) has no answer for
    the ordinary lifecycle of a real signing key: introducing a new one,
    retiring an old one without invalidating everything it already signed,
    or revoking a key outright if it may have been compromised. This ring
    holds any number of keys, each with a stable ``key_id`` and a status:

    - At most one ACTIVE key at a time (enforced by add_key: adding a new
      ACTIVE key retires the previous one automatically).
    - RETIRED keys still verify successfully -- rotating out a key must not
      break verification of receipts legitimately signed while it was live.
    - REVOKED keys fail verification outright, even for a receipt that was
      signed while the key was still active -- the operational lever for
      "this key may be compromised, stop trusting anything signed with it,"
      which retiring alone cannot express.

    Only public keys and metadata are held here, never a private key --
    matching sign_receipt's existing model of keeping the private key
    wherever the caller already keeps it (a paladin vault, an
    operator-only file), never in-process state shared with verifiers.
    """

    def __init__(self) -> None:
        self._entries: dict[str, KeyRingEntry] = {}

    def add_key(self, key_id: str, public_key_hex: str,
               status: KeyStatus = KeyStatus.ACTIVE) -> None:
        if not key_id:
            raise ValueError("key_id must be non-empty")
        if key_id in self._entries:
            raise ValueError(f"key_id {key_id!r} already exists in this ring")
        if status == KeyStatus.ACTIVE:
            for entry in self._entries.values():
                if entry.status == KeyStatus.ACTIVE:
                    entry.status = KeyStatus.RETIRED
        self._entries[key_id] = KeyRingEntry(key_id, public_key_hex, status)

    def retire(self, key_id: str) -> None:
        self._entries[key_id].status = KeyStatus.RETIRED

    def revoke(self, key_id: str) -> None:
        self._entries[key_id].status = KeyStatus.REVOKED

    def active_key_id(self) -> Optional[str]:
        for entry in self._entries.values():
            if entry.status == KeyStatus.ACTIVE:
                return entry.key_id
        return None

    def entry_for_public_key(self, public_key_hex: str) -> Optional[KeyRingEntry]:
        for entry in self._entries.values():
            if entry.public_key_hex == public_key_hex:
                return entry
        return None

    def to_dict(self) -> dict:
        return {
            key_id: {"public_key_hex": e.public_key_hex, "status": e.status.value}
            for key_id, e in self._entries.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SigningKeyRing":
        ring = cls()
        for key_id, e in data.items():
            ring._entries[key_id] = KeyRingEntry(
                key_id=key_id, public_key_hex=e["public_key_hex"],
                status=KeyStatus(e["status"]),
            )
        return ring

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True))

    @classmethod
    def load(cls, path: Path) -> "SigningKeyRing":
        return cls.from_dict(json.loads(path.read_text()))


def verify_signed_with_keyring(signed: dict, keyring: SigningKeyRing) -> bool:
    """Verify a signed envelope against a rotation-aware SigningKeyRing
    instead of one hardcoded expected key.

    Same checks as verify_signed() (fingerprint integrity, signature
    validity), plus: the embedded public key must be a key this ring
    actually knows about, and its status must not be REVOKED. A RETIRED
    key still verifies -- that's the entire point of retiring rather than
    revoking. An unknown public key (not in the ring at all) is rejected,
    same as an unrecognized key would be against a single expected key.
    """
    _require_crypto()
    from custodian.receipt import GovernedReceipt

    try:
        receipt = GovernedReceipt(**signed["receipt"])
    except (TypeError, KeyError):
        return False
    if not receipt.verify():
        return False

    public_key = signed.get("public_key", "")
    entry = keyring.entry_for_public_key(public_key)
    if entry is None or entry.status == KeyStatus.REVOKED:
        return False
    return verify_fingerprint(receipt.fingerprint, signed.get("signature", ""), public_key)
