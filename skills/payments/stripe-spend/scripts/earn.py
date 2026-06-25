#!/usr/bin/env python3
"""Real revenue in -- the deliberate asymmetry to spend.py/refund.py.

Spending is gated by bands/caps because money leaving the business is the
risk an agent could get wrong. Refunding is gated unconditionally because
reversing a charge is a different risk shape again. Earning -- a customer
paying the business -- has neither risk: an agent cannot harm the business
by receiving more real money. So this script has no band, no per-action
cap, no session cap, and no approval path. It only checks the same kill
switch spend.py/refund.py check, because a kill switch means "stop the
agent from doing anything as itself," not just "stop it from spending" --
a compromised agent fraudulently billing a real customer is still a real
problem even though the money would flow the safe direction.
"""
import argparse
import sqlite3
import sys

import _core


def _check_kill_switch():
    db_path = _core.SKILL_DIR / "state" / "custodian.db"
    if not db_path.exists():
        return False, "", ""
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT killed, reason, by FROM kill_switch WHERE id = 1").fetchone()
        conn.close()
        if row is None:
            return False, "", ""
        return bool(row[0]), row[1] or "", row[2] or ""
    except sqlite3.Error:
        return False, "", ""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--amount", type=float, required=True, help="USD amount earned")
    p.add_argument("--description", required=True)
    args = p.parse_args()

    killed, kill_reason, kill_by = _check_kill_switch()
    if killed:
        _core.append_log({
            "event": "earn_denied", "amount": args.amount, "description": args.description,
            "denied_by": kill_by or "operator",
            "reason": f"kill switch engaged: {kill_reason}" if kill_reason else "kill switch engaged",
        })
        print(f"[authority] DENIED — kill switch is engaged (by {kill_by or 'operator'}"
              f"{f', reason: ' + kill_reason if kill_reason else ''}).")
        print("[authority] This overrides every action, with no exceptions. "
              "Run `kill_toggle.py release --by <name>` to release it.")
        sys.exit(3)

    if args.amount < 0.50:
        print(f"[authority] REJECTED — ${args.amount:.2f} is below Stripe's $0.50 USD minimum charge.")
        sys.exit(1)

    print(f"[authority] earning is unrestricted by design (no band, no cap) — executing")
    ok = _core.execute_earn(args.amount, args.description)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
