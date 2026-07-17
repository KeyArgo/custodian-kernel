"""Ed25519 receipt signing — authenticity, not just integrity."""
import pytest

from custodian.receipt import GovernedReceipt
from custodian.signing import (
    generate_keypair,
    public_key_for,
    sign_receipt,
    verify_signed,
    verify_fingerprint,
    sign_fingerprint,
)


def _receipt(**kw):
    base = dict(
        fn_name="charge", band="L2", amount=5.00, description="api credits",
        verdict="autonomous", reason="ok", elapsed_ms=1.0, output={"ok": True},
        claim_proof="verified",
    )
    base.update(kw)
    return GovernedReceipt.build(**base)


def test_keypair_roundtrip():
    priv, pub = generate_keypair()
    assert public_key_for(priv) == pub
    assert len(bytes.fromhex(priv)) == 32 and len(bytes.fromhex(pub)) == 32


def test_signed_receipt_verifies():
    priv, pub = generate_keypair()
    signed = sign_receipt(_receipt(), priv)
    assert verify_signed(signed)
    assert verify_signed(signed, expected_public_key_hex=pub)


def test_tampering_a_signed_field_fails():
    priv, _ = generate_keypair()
    signed = sign_receipt(_receipt(), priv)
    signed["receipt"]["amount"] = 999.0  # break the fingerprint
    assert verify_signed(signed) is False


def test_forgery_with_attacker_key_is_rejected():
    """The core authenticity guarantee: an attacker who fabricates a receipt
    and signs it with their own key cannot pass verification against the
    kernel's known public key."""
    kernel_priv, kernel_pub = generate_keypair()
    attacker_priv, _ = generate_keypair()

    # Attacker builds a fraudulent receipt and signs it with their own key,
    # re-keying the fingerprint so the receipt's own verify() passes.
    fraud = _receipt(amount=1_000_000.0, claim_proof="verified")
    forged = sign_receipt(fraud, attacker_priv)

    # Verifying against the KERNEL's public key must fail.
    assert verify_signed(forged, expected_public_key_hex=kernel_pub) is False


def test_signature_does_not_verify_under_wrong_key():
    priv, _ = generate_keypair()
    _, other_pub = generate_keypair()
    r = _receipt()
    sig = sign_fingerprint(r.fingerprint, priv)
    assert verify_fingerprint(r.fingerprint, sig, other_pub) is False


def test_receipt_object_is_untouched_by_signing():
    priv, _ = generate_keypair()
    r = _receipt()
    fp_before = r.fingerprint
    sign_receipt(r, priv)
    assert r.fingerprint == fp_before  # detached signature, no mutation
