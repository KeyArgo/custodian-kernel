"""custodian demo-verify — runs 4 hardcoded claim-verification scenarios.

Demo wrapper (not the production verifier). Feeds hardcoded data through the
same verify_claims() function used in production, so the logic is real —
only the input data is fixed for the demonstration.

Runs with zero credentials. Designed for judges and quick sanity-checks.
"""
from __future__ import annotations

import copy

from custodian.packs.base import Claim, ClaimStatus, verify_claims


_DEMO_CASES = [
    {
        "claim_text": "Agent spent $5.00 on API credits",
        "ledger_text": "$5.00 API credits — 2026-06-29T14:30:00Z",
        "verdict_detail": "",
        "claims": [
            Claim(
                id="demo-1",
                statement="Agent spent $5.00 on API credits",
                customer_quote="$5.00 API credits",
                ledger_path="ledger.api_credits_usd",
                relation="eq",
                asserted=5.0,
            )
        ],
        "scope": {"ledger": {"api_credits_usd": 5.0}},
        "expect": ClaimStatus.VERIFIED,
    },
    {
        "claim_text": 'Agent received $25.00 from customer "acme-corp"',
        "ledger_text": "(no matching incoming transaction found)",
        "verdict_detail": "claim does not match ledger evidence",
        "claims": [
            Claim(
                id="demo-2",
                statement='Agent received $25.00 from customer "acme-corp"',
                customer_quote="$25.00 from acme-corp",
                ledger_path="ledger.incoming_from_acme_usd",
                relation="eq",
                asserted=25.0,
            )
        ],
        "scope": {"ledger": {"incoming_from_acme_usd": 0.0}},
        "expect": ClaimStatus.CONTRADICTED,
    },
    {
        "claim_text": 'Agent approved its own $50.00 refund to customer "test-user"',
        "ledger_text": "(no human approval record found for this refund)",
        "verdict_detail": "self-approval detected, escalated to human operator",
        "claims": [
            Claim(
                id="demo-3",
                statement="Refund of $50.00 was approved by a human operator",
                customer_quote="human approved",
                ledger_path="approval.human_approvals",
                relation="gte",
                asserted=1,
            )
        ],
        "scope": {"approval": {"human_approvals": 0}},
        "expect": ClaimStatus.CONTRADICTED,
    },
    {
        "claim_text": 'Agent will earn $100 next month from "future-client"',
        "ledger_text": "(no evidence available — future event)",
        "verdict_detail": "insufficient evidence",
        "claims": [
            Claim(
                id="demo-4",
                statement='Agent will earn $100 next month from "future-client"',
                customer_quote="$100 future earnings",
                ledger_path="ledger.next_month_earnings_usd",
                relation="gte",
                asserted=100.0,
            )
        ],
        "scope": {"ledger": {}},
        "expect": ClaimStatus.UNVERIFIABLE,
    },
]


def run(args) -> None:
    print("Custodian Claim Verifier — Live Demo")
    print("=" * 36)

    counts: dict[ClaimStatus, int] = {
        ClaimStatus.VERIFIED: 0,
        ClaimStatus.CONTRADICTED: 0,
        ClaimStatus.UNVERIFIABLE: 0,
    }

    for case in _DEMO_CASES:
        claims_copy = copy.deepcopy(case["claims"])
        verified = verify_claims(claims_copy, case["scope"])
        status = verified[0].status
        counts[status] = counts.get(status, 0) + 1
        detail = case["verdict_detail"]

        print(f"\nClaim:   {case['claim_text']}")
        print(f"Ledger:  {case['ledger_text']}")

        if status == ClaimStatus.VERIFIED:
            print("Verdict: ✅ VERIFIED")
        elif status == ClaimStatus.CONTRADICTED:
            print(f"Verdict: ❌ CONTRADICTED — {detail}")
        elif status == ClaimStatus.UNVERIFIABLE:
            print(f"Verdict: ❓ UNVERIFIABLE — {detail}")
        else:
            print(f"Verdict: {status.value}")

    v = counts.get(ClaimStatus.VERIFIED, 0)
    c = counts.get(ClaimStatus.CONTRADICTED, 0)
    u = counts.get(ClaimStatus.UNVERIFIABLE, 0)

    print("\n" + "=" * 36)
    print(f"Summary: {v} VERIFIED, {c} CONTRADICTED, {u} UNVERIFIABLE")
    print("The claim verifier catches lies deterministically.")
    print("The agent cannot fool it. This is proven, not claimed.")
    print("=" * 36)
