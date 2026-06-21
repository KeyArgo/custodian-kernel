#!/usr/bin/env python3
"""Authority-gated Stripe spend. See SKILL.md for usage.

This script can NEVER execute an over-cap amount, under any input — there is
no --approved-by flag here, deliberately. The only way past the cap is
approve.py, which performs a real Twilio Verify check it cannot fake, then
calls the privileged executor itself. That split is the actual safety
boundary, not a convention this script could be talked out of.
"""
import argparse
import sys
import time

import _core


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--amount", type=float, required=True, help="USD amount to spend")
    p.add_argument("--description", required=True)
    p.add_argument("--denied-by", default=None, help="Human operator name, to log a denial")
    p.add_argument("--recipe", default=None)
    p.add_argument("--to", default=None)
    p.add_argument("--message", default=None)
    args = p.parse_args()

    if args.amount < 0.50 and not args.denied_by:
        print(f"[authority] REJECTED — ${args.amount:.2f} is below Stripe's $0.50 USD minimum charge. "
              "Use an amount >= $0.50, or this is not a real chargeable action.")
        sys.exit(1)

    if args.denied_by:
        _core.append_log({
            "event": "denied", "amount": args.amount, "description": args.description,
            "denied_by": args.denied_by, "band": _core.load_state()["band"],
        })
        print(f"[audit] logged: denied (by {args.denied_by})")
        print("No Stripe call made.")
        return

    state = _core.load_state()
    cap = state["per_action_cap"]
    session_remaining = state["session_cap"] - state["spent_this_session"]
    over_cap = args.amount > cap
    over_session = args.amount > session_remaining

    if over_cap or over_session:
        import notify
        reason = []
        if over_cap:
            reason.append(f"${args.amount:.2f} exceeds per-action cap ${cap:.2f}")
        if over_session:
            reason.append(f"${args.amount:.2f} exceeds remaining session budget ${session_remaining:.2f}")
        reason_str = "; ".join(reason)

        notify.write_pending(args.amount, args.description, reason_str)
        notify.send_approval_code(args.amount, args.description)

        _core.append_log({
            "event": "escalation_required", "amount": args.amount, "description": args.description,
            "band": state["band"], "reason": reason_str,
        })
        print(f"[authority] {state['band']} cap exceeded — {reason_str}")
        print("[authority] ESCALATION REQUIRED — this exceeds the current authority band.")
        print("[authority] A one-time approval code has been sent to the human operator's phone via Twilio Verify.")
        print("[audit] logged: escalation_required")
        print("This script cannot proceed past this point under any circumstances — there is no "
              "override flag. The human must run `approve.py <code-from-their-phone> --approved-by <name>`.")
        sys.exit(2)

    print(f"[authority] {state['band']} cap OK (${args.amount:.2f} <= ${session_remaining:.2f} remaining) — executing autonomously")
    ok = _core.execute_spend(args.amount, args.description, approved_by=None,
                              recipe=args.recipe, to=args.to, message=args.message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
