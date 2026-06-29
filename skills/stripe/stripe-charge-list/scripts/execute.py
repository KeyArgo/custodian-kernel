#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.parse, base64
p = argparse.ArgumentParser()
p.add_argument("--limit", type=int, default=10)
p.add_argument("--customer", default=None)
a = p.parse_args()
key = os.environ.get("STRIPE_SECRET_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "stripe-charge-list", "message": "Set STRIPE_SECRET_KEY to enable"})); exit(0)
try:
    params = {"limit": str(a.limit)}
    if a.customer: params["customer"] = a.customer
    url = "https://api.stripe.com/v1/charges?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    charges = [{"id": c["id"], "amount": c["amount"], "currency": c["currency"], "status": c["status"]} for c in d.get("data", [])]
    print(json.dumps({"ok": True, "tool": "stripe-charge-list", "charges": charges, "count": len(charges)}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "stripe-charge-list", "error": str(e)}))
