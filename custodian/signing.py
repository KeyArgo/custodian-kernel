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
    assert verify_signed(signed, pub)             # False if forged or re-keyed

Requires the ``cryptography`` package (a base dependency of custodian-kernel).
"""
from __future__ import annotations

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


def sign_receipt(receipt, private_key_hex: str) -> dict:
    """Return a detached signed envelope for ``receipt``.

    The receipt object is not modified. The envelope carries the receipt dict,
    the signature over its fingerprint, and the public key needed to verify.
    """
    _require_crypto()
    return {
        "receipt": receipt.to_dict(),
        "signature": sign_fingerprint(receipt.fingerprint, private_key_hex),
        "public_key": public_key_for(private_key_hex),
        "alg": "Ed25519",
    }


def verify_signed(signed: dict, expected_public_key_hex: Optional[str] = None) -> bool:
    """Verify a signed envelope end to end.

    Checks (1) the receipt's own fingerprint is intact, (2) the signature is
    valid for that fingerprint, and (3) — if ``expected_public_key_hex`` is
    given — that the receipt was signed by exactly that key (so an attacker
    cannot re-sign forged data with their own key and swap in their public
    key). Returns False on any failure.
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
    if expected_public_key_hex is not None and public_key != expected_public_key_hex:
        return False
    return verify_fingerprint(receipt.fingerprint, signed.get("signature", ""), public_key)
