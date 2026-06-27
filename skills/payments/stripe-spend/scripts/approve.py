#!/usr/bin/env python3
"""Approve a pending escalated spend using the real Twilio Verify code sent
to the operator's phone. This is the ONLY script that can execute an
over-cap spend — and only after Twilio itself confirms the code is correct.
"""
import argparse
import json
import sys
import time

import _core
import notify

PENDING_FILE = _core.SKILL_DIR / "state" / "pending_approval.json"
PENDING_TTL_SECONDS = 600


def main():
    p = argparse.ArgumentParser()
    p.add_argument("code", help="The approval code received via real SMS (Twilio Verify)")
    p.add_argument("--approved-by", required=True, help="Human operator name")
    args = p.parse_args()

    if not PENDING_FILE.exists():
        print("[approve] No pending escalation found.")
        sys.exit(1)

    record = json.loads(PENDING_FILE.read_text())
    if time.time() - record["created_at"] > PENDING_TTL_SECONDS:
        PENDING_FILE.unlink()
        print(f"[approve] Pending escalation expired ({PENDING_TTL_SECONDS}s TTL). "
              f"Ask the agent to retry the spend.")
        sys.exit(1)

    if not notify.check_approval_code(args.code):
        print("[approve] Code rejected by Twilio Verify — wrong code or already used.")
        sys.exit(1)

    kind_label = record.get("kind", "spend")
    print(f"[approve] About to execute: {kind_label} ${record['amount']:.2f} -- {record['description']}"
          + (f" (refunding {record['payment_intent_id']})" if kind_label == "refund" else ""))
    print("[approve] This is the exact request the Twilio code you just entered was sent for. "
          "Verify it matches what you intended to approve before this line.")

    PENDING_FILE.unlink()
    print(f"[authority] Twilio Verify confirmed — executing with human approval (by {args.approved_by})")
    kind = record.get("kind", "spend")
    if kind == "refund":
        ok = _core.execute_refund(record["payment_intent_id"], record["amount"], record["description"],
                                   approved_by=args.approved_by)
    else:
        ok = _core.execute_spend(record["amount"], record["description"], approved_by=args.approved_by)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
