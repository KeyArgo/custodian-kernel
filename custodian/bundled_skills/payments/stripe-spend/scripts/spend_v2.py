#!/usr/bin/env python3
"""Authority-gated Stripe spend -- thin wrapper over the custodian package.

This script can NEVER execute an over-cap amount, under any input -- there is
no --approved-by flag here, deliberately. The only way past the cap is
approve.py, which performs a real Twilio Verify check it cannot fake, then
calls the privileged executor itself. That split is the actual safety
boundary, not a convention this script could be talked out of.

This is spend_v2.py, not a replacement for spend.py yet -- it produces
identical decisions (verified by tests against the original), routed through
the custodian.policy engine instead of a hardcoded comparison, so the same
decision logic is now configurable per-policy and independently testable.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))  # repo root, for `import custodian`

import _core
from custodian.policy import decide, load_policy
from custodian.types import SpendRequest, Verdict

POLICY_PATH = Path(__file__).resolve().parent.parent / "policy.yaml"


def _state_to_authority_state():
    from custodian.types import AuthorityState
    return AuthorityState.from_dict(_core.load_state())


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

    policy = load_policy(POLICY_PATH)
    state = _state_to_authority_state()
    request = SpendRequest(amount=args.amount, description=args.description,
                            recipe=args.recipe, to=args.to, message=args.message)
    decision = decide(request, state, policy)

    if decision.verdict == Verdict.ESCALATION_REQUIRED:
        import notify
        notify.write_pending(args.amount, args.description, decision.reason)
        notify.send_approval_code(args.amount, args.description)

        _core.append_log({
            "event": "escalation_required", "amount": args.amount, "description": args.description,
            "band": decision.band.value, "reason": decision.reason,
        })
        print(f"[authority] {decision.band.value} cap exceeded — {decision.reason}")
        print("[authority] ESCALATION REQUIRED — this exceeds the current authority band.")
        print("[authority] A one-time approval code has been sent to the human operator's phone via Twilio Verify.")
        print("[audit] logged: escalation_required")
        print("This script cannot proceed past this point under any circumstances — there is no "
              "override flag. The human must run `approve.py <code-from-their-phone> --approved-by <name>`.")
        sys.exit(2)

    raw_state = _core.load_state()
    session_remaining = raw_state["session_cap"] - raw_state["spent_this_session"]
    print(f"[authority] {decision.band.value} cap OK (${args.amount:.2f} <= ${session_remaining:.2f} remaining) — executing autonomously")
    ok = _core.execute_spend(args.amount, args.description, approved_by=None,
                              recipe=args.recipe, to=args.to, message=args.message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
