"""Tests for GovernedReceipt."""
import json
import hashlib

from custodian.receipt import GovernedReceipt


def test_build_and_verify():
    receipt = GovernedReceipt.build(
        fn_name="charge_customer", band="L2", amount=25.00,
        description="charge_customer", verdict="autonomous",
        reason="within cap", elapsed_ms=12.4, output={"charged": 25.00},
    )
    assert receipt.verify()


def test_tamper_detected():
    receipt = GovernedReceipt.build(
        fn_name="fn", band="L2", amount=10.00,
        description="fn", verdict="autonomous",
        reason="ok", elapsed_ms=1.0, output={"ok": True},
    )
    assert receipt.verify()

    # Tamper with verdict — must fail
    object.__setattr__(receipt, "verdict", "denied")
    assert not receipt.verify()
    object.__setattr__(receipt, "verdict", "autonomous")

    # Tamper with amount — must also fail (amount is in the fingerprint)
    object.__setattr__(receipt, "amount", 9999.00)
    assert not receipt.verify()
    object.__setattr__(receipt, "amount", 10.00)

    # Tamper with band — must also fail
    object.__setattr__(receipt, "band", "L0")
    assert not receipt.verify()
    object.__setattr__(receipt, "band", "L2")

    # Fully restored — must pass again
    assert receipt.verify()


def test_to_json_roundtrip():
    receipt = GovernedReceipt.build(
        fn_name="fn", band="L1", amount=0.50,
        description="fn", verdict="autonomous",
        reason="trivial", elapsed_ms=2.0, output=None,
    )
    raw = json.loads(receipt.to_json())
    assert raw["band"] == "L1"
    assert raw["verdict"] == "autonomous"
    assert "fingerprint" in raw
    assert "receipt_id" in raw


def test_output_hash_deterministic():
    output = {"charged": 25.00, "customer": "cus_123"}
    expected_hash = hashlib.sha256(
        json.dumps(output, default=str, sort_keys=True).encode()
    ).hexdigest()
    receipt = GovernedReceipt.build(
        fn_name="fn", band="L2", amount=25.00,
        description="fn", verdict="autonomous",
        reason="ok", elapsed_ms=0.0, output=output,
    )
    assert receipt.output_hash == expected_hash


def test_fingerprint_is_cross_platform_deterministic():
    """Receipt hashing must be byte-identical on every OS (Windows, Linux,
    macOS) and CI. output_hash covers the payload — the non-ASCII 'café'
    guards against encoding drift (json ensure_ascii keeps it stable). The
    fingerprint is checked via _compute_fingerprint with a fixed receipt_id,
    because a live receipt_id is a random uuid. A change to either golden
    value means receipts are no longer reproducible across platforms."""
    r = GovernedReceipt.build(
        fn_name="charge", band="L2", amount=5.0, description="api credits",
        verdict="autonomous", reason="ok", elapsed_ms=0.0,
        output={"ok": True, "items": [1, 2, 3], "note": "café"},
        claim_proof="verified",
    )
    assert r.output_hash == "d1fa9fe487cf291c6f2836fab86c362fc0e6d24a00d25ccce692a5820f9c8c6a"

    fp = GovernedReceipt._compute_fingerprint(
        "fixed-receipt-id", "charge", "L2", 5.0, "autonomous", "ok",
        "api credits", "verified", r.output_hash,
    )
    assert fp == "22c122905f0cb216bd02408d3ba3e5e1e0336c5c591e3036d3abdee2ffdab4ab"


def test_claim_proof_none_by_default():
    receipt = GovernedReceipt.build(
        fn_name="fn", band="L2", amount=1.00,
        description="fn", verdict="autonomous",
        reason="ok", elapsed_ms=0.0, output={},
    )
    assert receipt.claim_proof is None


def test_claim_proof_included():
    receipt = GovernedReceipt.build(
        fn_name="fn", band="L2", amount=1.00,
        description="fn", verdict="autonomous",
        reason="ok", elapsed_ms=0.0, output={},
        claim_proof="verified",
    )
    assert receipt.claim_proof == "verified"
    assert receipt.verify()


def test_claim_proof_is_tamper_sensitive():
    """A receipt cannot be forged to claim it passed verification when it did
    not — claim_proof is inside the fingerprint."""
    receipt = GovernedReceipt.build(
        fn_name="fn", band="L2", amount=1.00,
        description="fn", verdict="autonomous",
        reason="ok", elapsed_ms=0.0, output={},
        claim_proof="contradicted",
    )
    assert receipt.verify()
    object.__setattr__(receipt, "claim_proof", "verified")
    assert not receipt.verify()
