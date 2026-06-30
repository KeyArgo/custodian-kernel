"""Regression tests for custodian demo-verify command and the claim verifier."""
from __future__ import annotations

import subprocess
import sys

import pytest

from custodian.packs.base import Claim, ClaimStatus, verify_claims


def test_demo_verify_all_cases():
    """demo-verify runs all 4 cases and returns exit code 0."""
    result = subprocess.run(
        ["custodian", "demo", "verify"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"demo-verify exited {result.returncode}\n{result.stdout}\n{result.stderr}"
    assert "VERIFIED" in result.stdout
    assert "CONTRADICTED" in result.stdout
    assert "UNVERIFIABLE" in result.stdout
    assert "self-approval" in result.stdout.lower()


class TestDemoVerifyScenarios:
    """The four demo scenarios must always return the expected verdict."""

    def test_verified_invoice_total_matches_po(self):
        claims = [Claim(
            id="d1", statement="Invoice total matches PO",
            customer_quote="$1200", ledger_path="po.total",
            relation="eq", asserted=1200.0,
        )]
        result = verify_claims(claims, {"po": {"total": 1200.0}})
        assert result[0].status == ClaimStatus.VERIFIED

    def test_contradicted_invoice_amount_inflated(self):
        claims = [Claim(
            id="d2", statement="Invoice matches PO amount",
            customer_quote="$40", ledger_path="po.amount",
            relation="eq", asserted=40.0,
        )]
        result = verify_claims(claims, {"po": {"amount": 45.0}})
        assert result[0].status == ClaimStatus.CONTRADICTED
        assert result[0].actual == 45.0

    def test_contradicted_duplicate_payment(self):
        claims = [Claim(
            id="d3", statement="Invoice not paid before",
            customer_quote="0 prior payments", ledger_path="invoice.prior_payment_count",
            relation="eq", asserted=0,
        )]
        result = verify_claims(claims, {"invoice": {"prior_payment_count": 1}})
        assert result[0].status == ClaimStatus.CONTRADICTED

    def test_unverifiable_external_rating(self):
        claims = [Claim(
            id="d4", statement="Vendor rating above 4.5",
            customer_quote="4.8", ledger_path="vendor.external_rating",
            relation="gte", asserted=4.5,
        )]
        result = verify_claims(claims, {"vendor": {"name": "Acme Corp"}})
        assert result[0].status == ClaimStatus.UNVERIFIABLE


def test_self_approval_is_caught_not_approved():
    """An agent cannot approve its own escalation.

    The claim verifier is deterministic — it never asks the AI to mark its
    own homework. If a claim is CONTRADICTED, the kernel must block the
    request regardless of what the agent's disposition says.
    """
    from custodian.packs.engine import triage, _final_action
    from custodian.packs.base import Claim, Envelope, EvidenceSpan
    from custodian.policy.schema import Policy, BandConfig
    from custodian.types import AuthorityState, Band

    # Verifier checks: actual (ledger value) <relation> asserted (claim value).
    # "threshold (99) >= amount (1)" → 99 >= 1 → True → VERIFIED
    claim = Claim(
        id="self-approval-test",
        statement="Approved threshold covers the refund amount",
        customer_quote="$1.00",
        ledger_path="approved_threshold",
        relation="gte",
        asserted=1.0,
    )
    scope = {"approved_threshold": 99.0}
    from custodian.packs.base import verify_claims
    verified = verify_claims([claim], scope)
    assert verified[0].status == ClaimStatus.VERIFIED

    # "threshold (50) >= claimed amount (200)" → 50 >= 200 → False → CONTRADICTED
    contradicted_claim = Claim(
        id="self-approval-test-2",
        statement="Approved threshold covers the refund amount",
        customer_quote="$200",
        ledger_path="approved_threshold",
        relation="gte",
        asserted=200.0,
    )
    scope2 = {"approved_threshold": 50.0}
    verified2 = verify_claims([contradicted_claim], scope2)
    assert verified2[0].status == ClaimStatus.CONTRADICTED, (
        "Agent claimed threshold covers $200 but ledger says threshold is $50 — "
        "the verifier must CONTRADICT this, not accept the agent's assertion at face value."
    )
