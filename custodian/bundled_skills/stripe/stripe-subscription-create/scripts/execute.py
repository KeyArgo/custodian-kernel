#!/usr/bin/env python3
import argparse, json, os, requests

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--customer-id", required=True)
    p.add_argument("--price-id", required=True)
    p.add_argument("--trial-days", type=int, default=0)
    a = p.parse_args()
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        print(json.dumps({"ok": False, "stub": True, "tool": "stripe-subscription-create", "message": "Set STRIPE_SECRET_KEY"})); return
    try:
        payload = {"customer": a.customer_id, "items": [{"price": a.price_id}]}
        if a.trial_days > 0:
            payload["trial_period_days"] = a.trial_days
        r = requests.post("https://api.stripe.com/v1/subscriptions",
            auth=(key, ""), data=payload, timeout=15)
        d = r.json()
        if not r.ok:
            print(json.dumps({"ok": False, "tool": "stripe-subscription-create", "error": d.get("error", {}).get("message", str(d))})); return
        print(json.dumps({"ok": True, "tool": "stripe-subscription-create",
            "subscription_id": d.get("id"), "status": d.get("status"),
            "customer": d.get("customer"), "current_period_end": d.get("current_period_end")}))
    except Exception as e:
        print(json.dumps({"ok": False, "tool": "stripe-subscription-create", "error": str(e)}))

if __name__ == "__main__": main()
