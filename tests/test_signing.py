"""Ed25519 receipt signing — authenticity, not just integrity."""
import pytest

from custodian.receipt import GovernedReceipt
from custodian.signing import (
    KeyStatus,
    SigningKeyRing,
    generate_keypair,
    public_key_for,
    sign_receipt,
    verify_signed,
    verify_signed_with_keyring,
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
    assert verify_signed(signed, expected_public_key_hex=pub)


def test_tampering_a_signed_field_fails():
    priv, pub = generate_keypair()
    signed = sign_receipt(_receipt(), priv)
    signed["receipt"]["amount"] = 999.0  # break the fingerprint
    assert verify_signed(signed, expected_public_key_hex=pub) is False


def test_expected_public_key_hex_is_required():
    """verify_signed used to default expected_public_key_hex to None, which
    skipped the one check that makes this an authenticity guarantee rather
    than an internal-consistency check: an attacker who fabricates a
    receipt, signs it with their own throwaway key, and embeds that key in
    the envelope passed verification, because "verify against whatever key
    claims to have signed it" proves nothing. Now required -- there is no
    legitimate call that doesn't know which key it trusts. Found in
    review."""
    priv, _ = generate_keypair()
    signed = sign_receipt(_receipt(), priv)
    with pytest.raises(TypeError):
        verify_signed(signed)


def test_forged_receipt_with_its_own_embedded_key_is_rejected():
    """The exact bypass: attacker signs a fabricated receipt with their own
    key and the envelope self-reports that key as legitimate. Verification
    against the kernel's real public key -- the only call this function
    now allows -- must reject it."""
    kernel_priv, kernel_pub = generate_keypair()
    attacker_priv, attacker_pub = generate_keypair()
    fraud = _receipt(amount=1_000_000.0)
    forged = sign_receipt(fraud, attacker_priv)  # envelope's public_key == attacker_pub
    assert forged["public_key"] == attacker_pub
    assert verify_signed(forged, expected_public_key_hex=kernel_pub) is False


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


# ── SigningKeyRing — rotation-ready key management ─────────────────────────

def test_adding_a_new_active_key_retires_the_previous_one():
    priv1, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    ring = SigningKeyRing()
    ring.add_key("k1", pub1)
    ring.add_key("k2", pub2)
    assert ring.entry_for_public_key(pub1).status == KeyStatus.RETIRED
    assert ring.entry_for_public_key(pub2).status == KeyStatus.ACTIVE
    assert ring.active_key_id() == "k2"


def test_retired_key_still_verifies_old_receipts():
    old_priv, old_pub = generate_keypair()
    _, new_pub = generate_keypair()
    ring = SigningKeyRing()
    ring.add_key("old", old_pub)   # active when this receipt was signed
    signed = sign_receipt(_receipt(), old_priv, key_id="old")
    ring.add_key("new", new_pub)   # rotation: "old" is now retired

    assert ring.entry_for_public_key(old_pub).status == KeyStatus.RETIRED
    assert verify_signed_with_keyring(signed, ring) is True


def test_revoked_key_fails_verification_even_for_a_previously_valid_receipt():
    """Revoking is the lever retiring cannot express: "this key may be
    compromised, stop trusting anything signed with it" -- even a receipt
    that was legitimately signed while the key was active must now fail."""
    priv, pub = generate_keypair()
    ring = SigningKeyRing()
    ring.add_key("compromised", pub)
    signed = sign_receipt(_receipt(), priv, key_id="compromised")
    assert verify_signed_with_keyring(signed, ring) is True  # valid before revocation

    ring.revoke("compromised")
    assert verify_signed_with_keyring(signed, ring) is False


def test_unknown_key_is_rejected():
    """A receipt signed with a key the ring has never heard of must fail --
    same as an unrecognized key would against a single expected key."""
    stranger_priv, _ = generate_keypair()
    ring = SigningKeyRing()
    _, known_pub = generate_keypair()
    ring.add_key("known", known_pub)

    signed = sign_receipt(_receipt(), stranger_priv, key_id="stranger")
    assert verify_signed_with_keyring(signed, ring) is False


def test_keyring_persists_and_reloads(tmp_path):
    _, pub1 = generate_keypair()
    _, pub2 = generate_keypair()
    ring = SigningKeyRing()
    ring.add_key("k1", pub1)
    ring.add_key("k2", pub2)
    ring.revoke("k1")

    path = tmp_path / "keyring.json"
    ring.save(path)
    reloaded = SigningKeyRing.load(path)

    assert reloaded.entry_for_public_key(pub1).status == KeyStatus.REVOKED
    assert reloaded.entry_for_public_key(pub2).status == KeyStatus.ACTIVE
    assert reloaded.active_key_id() == "k2"


def test_duplicate_key_id_rejected():
    ring = SigningKeyRing()
    _, pub = generate_keypair()
    ring.add_key("k1", pub)
    with pytest.raises(ValueError):
        ring.add_key("k1", pub)
