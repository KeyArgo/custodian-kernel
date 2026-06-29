#!/usr/bin/env python3
import argparse, json, os, requests

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--subscription-id", required=True)
    p.add_argument("--at-period-end", action="store_true",
                   help="Cancel at end of current period instead of immediately")
    a = p.parse_args()
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        print(json.dumps({"ok": False, "stub": True, "tool": "stripe-subscription-cancel", "message": "Set STRIPE_SECRET_KEY"})); return
    try:
        if a.at_period_end:
            r = requests.post(f"https://api.stripe.com/v1/subscriptions/{a.subscription_id}",
                auth=(key, ""), data={"cancel_at_period_end": "true"}, timeout=15)
        else:
            r = requests.delete(f"https://api.stripe.com/v1/subscriptions/{a.subscription_id}",
                auth=(key, ""), timeout=15)
        d = r.json()
        if not r.ok:
            print(json.dumps({"ok": False, "tool": "stripe-subscription-cancel", "error": d.get("error", {}).get("message", str(d))})); return
        print(json.dumps({"ok": True, "tool": "stripe-subscription-cancel",
            "subscription_id": d.get("id"), "status": d.get("status"),
            "cancel_at_period_end": d.get("cancel_at_period_end"),
            "canceled_at": d.get("canceled_at")}))
    except Exception as e:
        print(json.dumps({"ok": False, "tool": "stripe-subscription-cancel", "error": str(e)}))

if __name__ == "__main__": main()
