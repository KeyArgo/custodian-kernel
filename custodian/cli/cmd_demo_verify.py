"""custodian demo-verify — runs 4 hardcoded claim-verification scenarios.

Shows VERIFIED, CONTRADICTED, and UNVERIFIABLE verdicts with no credentials
required. Intended for hackathon judges and quick sanity-checks.
"""
from __future__ import annotations

import copy

from custodian.packs.base import Claim, ClaimStatus, verify_claims


_DEMO_CASES = [
    {
        "label": "Invoice total matches PO (VERIFIED)",
        "claims": [
            Claim(
                id="demo-1",
                statement="Invoice total matches the approved purchase order",
                customer_quote="$1,200.00",
                ledger_path="po.total",
                relation="eq",
                asserted=1200.0,
            )
        ],
        "scope": {"po": {"total": 1200.0}},
        "expect": [ClaimStatus.VERIFIED],
    },
    {
        "label": "Invoice amount inflated — supplier billed $5 above PO (CONTRADICTED)",
        "claims": [
            Claim(
                id="demo-2",
                statement="Invoice amount matches the purchase order",
                customer_quote="$40.00",
                ledger_path="po.amount",
                relation="eq",
                asserted=40.0,
            )
        ],
        "scope": {"po": {"amount": 45.0}},
        "expect": [ClaimStatus.CONTRADICTED],
    },
    {
        "label": "Duplicate payment — prior payment count should be 0 (CONTRADICTED)",
        "claims": [
            Claim(
                id="demo-3",
                statement="This invoice has not been paid before (prior_payment_count == 0)",
                customer_quote="0 prior payments",
                ledger_path="invoice.prior_payment_count",
                relation="eq",
                asserted=0,
            )
        ],
        "scope": {"invoice": {"id": "INV-9981", "prior_payment_count": 1}},
        "expect": [ClaimStatus.CONTRADICTED],
    },
    {
        "label": "Vendor external rating — not in ledger (UNVERIFIABLE)",
        "claims": [
            Claim(
                id="demo-4",
                statement="Vendor has an external rating above 4.5 stars",
                customer_quote="4.8 stars",
                ledger_path="vendor.external_rating",
                relation="gte",
                asserted=4.5,
            )
        ],
        "scope": {"vendor": {"name": "Acme Corp"}},
        "expect": [ClaimStatus.UNVERIFIABLE],
    },
]

_STATUS_ICON = {
    ClaimStatus.VERIFIED: "VERIFIED",
    ClaimStatus.CONTRADICTED: "CONTRADICTED",
    ClaimStatus.UNVERIFIABLE: "UNVERIFIABLE",
    ClaimStatus.PENDING: "PENDING",
}

_STATUS_MARK = {
    ClaimStatus.VERIFIED: "✓",
    ClaimStatus.CONTRADICTED: "✗",
    ClaimStatus.UNVERIFIABLE: "?",
    ClaimStatus.PENDING: "·",
}


def run(args) -> None:
    print("Custodian Claim Verifier — demo mode")
    print("=" * 54)
    passed = 0
    failed = 0
    for case in _DEMO_CASES:
        claims_copy = copy.deepcopy(case["claims"])
        verified = verify_claims(claims_copy, case["scope"])
        case_passed = True
        print(f"\n  {case['label']}")
        for claim, expected in zip(verified, case["expect"]):
            icon = _STATUS_ICON.get(claim.status, claim.status.value)
            mark = _STATUS_MARK.get(claim.status, "·")
            ok = claim.status == expected
            if not ok:
                case_passed = False
            tick = "PASS" if ok else "FAIL"
            print(f"    [{tick}]  {mark} {icon}")
            print(f"           Statement : {claim.statement}")
            if claim.actual is not None:
                print(f"           Ledger    : {claim.actual!r}  (asserted: {claim.asserted!r})")
        if case_passed:
            passed += 1
        else:
            failed += 1
    print(f"\n{'=' * 54}")
    print(f"Results: {passed} passed, {failed} failed out of {len(_DEMO_CASES)} scenarios")
    if failed:
        raise SystemExit(1)
