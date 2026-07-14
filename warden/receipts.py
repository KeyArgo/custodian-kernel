"""Optional receipt co-signing — authenticity on top of the kernel's
integrity hash.

The kernel's :class:`custodian.receipt.GovernedReceipt` fingerprint is an
*unkeyed* SHA-256: it proves a receipt wasn't accidentally corrupted, but
not that it was issued by this system (anyone can recompute it). This
module adds an HMAC signature keyed by a Warden vault subkey, so a holder
of the key can distinguish a genuine receipt from a forged one —
non-repudiation for sites that need it, off by default for those that
don't.

This lives in ``warden`` (not the kernel) on purpose: the kernel stays
lean; authenticity is a modular add-on you opt into.

Usage::

    from warden.vault import Vault
    from warden.receipts import sign_receipt, verify_signed

    vault = Vault.open(passphrase=...)
    sig = sign_receipt(receipt, vault)          # hex HMAC
    assert verify_signed(receipt, sig, vault)   # True iff untampered+authentic
"""
from __future__ import annotations

import hashlib
import hmac

from warden import crypto


def _receipt_key(vault) -> bytes:
    # Distinct purpose from the audit key so the two constructions never
    # share key material.
    return crypto.subkey(vault._key, b"receipt")


def _receipt_body(receipt) -> bytes:
    """Canonical bytes over every tamper-sensitive receipt field.

    Covers more than the kernel fingerprint (which omits ts, fn_name,
    description, elapsed) so the signature binds the whole record.
    """
    d = receipt.to_dict() if hasattr(receipt, "to_dict") else dict(receipt)
    fields = ["receipt_id", "ts", "fn_name", "band", "amount", "description",
              "verdict", "reason", "elapsed_ms", "output_hash", "claim_proof"]
    parts = [f"{k}={d.get(k)!r}" for k in fields]
    return "\n".join(parts).encode("utf-8")


def sign_receipt(receipt, vault) -> str:
    """Return a hex HMAC-SHA256 signature binding the whole receipt."""
    return hmac.new(_receipt_key(vault), _receipt_body(receipt),
                    hashlib.sha256).hexdigest()


def verify_signed(receipt, signature: str, vault) -> bool:
    """True iff `signature` is a valid co-signature for `receipt`.

    Also requires the receipt's own integrity check (`verify()`) to pass
    when available, so a caller gets integrity + authenticity in one call.
    """
    if hasattr(receipt, "verify") and not receipt.verify():
        return False
    expected = sign_receipt(receipt, vault)
    return hmac.compare_digest(expected, signature or "")
