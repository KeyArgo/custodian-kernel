#!/usr/bin/env python3
import argparse, json, os, requests

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--amount", type=int, required=True, help="Amount in cents")
    p.add_argument("--currency", default="usd")
    p.add_argument("--description", default="")
    a = p.parse_args()
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        print(json.dumps({"ok": False, "stub": True, "tool": "stripe-payout", "message": "Set STRIPE_SECRET_KEY"})); return
    try:
        payload = {"amount": a.amount, "currency": a.currency}
        if a.description:
            payload["description"] = a.description
        r = requests.post("https://api.stripe.com/v1/payouts",
            auth=(key, ""), data=payload, timeout=15)
        d = r.json()
        if not r.ok:
            print(json.dumps({"ok": False, "tool": "stripe-payout", "error": d.get("error", {}).get("message", str(d))})); return
        print(json.dumps({"ok": True, "tool": "stripe-payout",
            "payout_id": d.get("id"), "amount": d.get("amount"),
            "currency": d.get("currency"), "status": d.get("status"),
            "arrival_date": d.get("arrival_date")}))
    except Exception as e:
        print(json.dumps({"ok": False, "tool": "stripe-payout", "error": str(e)}))

if __name__ == "__main__": main()
