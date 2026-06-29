#!/usr/bin/env python3
"""Approve a pending escalated spend -- thin wrapper over the custodian package.

This is the ONLY script that can execute an over-cap spend -- and only after
Twilio itself confirms the code is correct. This is approve_v2.py, not a
replacement for approve.py yet -- verified to produce identical behavior.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))  # repo root, for `import custodian`

import _core
import notify
from custodian.types import PendingApproval

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

    import json
    record = PendingApproval.from_dict(json.loads(PENDING_FILE.read_text()))
    if record.is_expired(PENDING_TTL_SECONDS):
        PENDING_FILE.unlink()
        print(f"[approve] Pending escalation expired ({PENDING_TTL_SECONDS}s TTL). "
              f"Ask the agent to retry the spend.")
        sys.exit(1)

    if not notify.check_approval_code(args.code):
        print("[approve] Code rejected by Twilio Verify — wrong code or already used.")
        sys.exit(1)

    PENDING_FILE.unlink()
    print(f"[authority] Twilio Verify confirmed — executing with human approval (by {args.approved_by})")
    ok = _core.execute_spend(record.amount, record.description, approved_by=args.approved_by)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
