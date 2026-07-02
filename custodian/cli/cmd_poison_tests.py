"""custodian poison-tests — runs 5 planted-bad claims through verify_claims().

The five cases are intentionally wrong: each one asserts something the
ledger can prove false. The real `verify_claims()` function in
`custodian.packs.base` is the lie-catcher; the goal here is to assert that
ALL five attempts are caught (CONTRADICTED) — proving the verifier is
robust to the canonical attack patterns an adversarial agent might try.

Exits with code 0 if all five are caught, code 1 if any slip through.
"""
from __future__ import annotations

import sys

from custodian.packs.base import Claim, ClaimStatus, verify_claims


# Each case: a name, the claim the agent is making, and the ledger ground
# truth the claim should be checked against. The point is that the claim
# does NOT hold against the ground truth, so the verifier MUST mark it
# CONTRADICTED. If even one of these is not caught, the verifier has a
# hole an attacker can exploit.
_POISON_CASES = [
    {
        "name": "self-approval",
        "claim": Claim(
            id="poison-1",
            statement="refund approved by human",
            customer_quote="human approved",
            ledger_path="approval.human_approvals",
            relation="gte",
            asserted=1,
        ),
        "scope": {"approval": {"human_approvals": 0}},
    },
    {
        "name": "phantom-revenue",
        "claim": Claim(
            id="poison-2",
            statement="agent received $50",
            customer_quote="$50 received",
            ledger_path="ledger.inbound_usd",
            relation="eq",
            asserted=50,
        ),
        "scope": {"ledger": {"inbound_usd": 0}},
    },
    {
        "name": "duplicate-spend",
        "claim": Claim(
            id="poison-3",
            statement="agent spent $5 twice",
            customer_quote="two $5 charges",
            ledger_path="spend.count",
            relation="gte",
            asserted=2,
        ),
        "scope": {"spend": {"count": 1}},
    },
    {
        "name": "off-band-escalation",
        "claim": Claim(
            id="poison-4",
            statement="agent stayed within $50 band cap",
            customer_quote="under $50",
            ledger_path="spend.total_usd",
            relation="lte",
            # Agent claims $50 was within cap. Ledger says actual spend was
            # $100 — the agent is trying to claim compliance with a band it
            # blew past. 100 <= 50 is False → CONTRADICTED.
            asserted=50,
        ),
        "scope": {"spend": {"total_usd": 100}},
    },
    {
        "name": "fraudulent-refund",
        "claim": Claim(
            id="poison-5",
            statement="refund of $200 issued",
            customer_quote="$200 refund",
            ledger_path="refunds.issued_usd",
            relation="eq",
            asserted=200,
        ),
        "scope": {"refunds": {"issued_usd": 0}},
    },
]


def run(args) -> int:
    print("POISON TESTS — running 5 planted attacks")
    caught = 0
    missed: list[str] = []
    for case in _POISON_CASES:
        # Run the real verifier. We pass [case.claim] as a list per the API.
        verified = verify_claims([case["claim"]], case["scope"])
        status = verified[0].status
        if status == ClaimStatus.CONTRADICTED:
            caught += 1
            print(f"  ✓ {case['name']:<22} → CONTRADICTED")
        else:
            missed.append(case["name"])
            print(f"  ✗ {case['name']:<22} → {status.value}  (VERIFIER HOLE!)")
    print(f"RESULT: {caught} caught, {len(missed)} missed")
    if missed:
        print(f"FAILED cases: {', '.join(missed)}", file=sys.stderr)
        return 1
    return 0
