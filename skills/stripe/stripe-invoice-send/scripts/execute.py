#!/usr/bin/env python3
import argparse, json, os, requests

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--invoice-id", required=True)
    a = p.parse_args()
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        print(json.dumps({"ok": False, "stub": True, "tool": "stripe-invoice-send", "message": "Set STRIPE_SECRET_KEY"})); return
    try:
        r = requests.post(f"https://api.stripe.com/v1/invoices/{a.invoice_id}/send",
            auth=(key, ""), timeout=15)
        d = r.json()
        if not r.ok:
            print(json.dumps({"ok": False, "tool": "stripe-invoice-send", "error": d.get("error", {}).get("message", str(d))})); return
        print(json.dumps({"ok": True, "tool": "stripe-invoice-send",
            "invoice_id": d.get("id"), "status": d.get("status"),
            "amount_due": d.get("amount_due"), "customer": d.get("customer")}))
    except Exception as e:
        print(json.dumps({"ok": False, "tool": "stripe-invoice-send", "error": str(e)}))

if __name__ == "__main__": main()
