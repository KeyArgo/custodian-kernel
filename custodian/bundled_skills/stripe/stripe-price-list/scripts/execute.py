#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.parse, base64
p = argparse.ArgumentParser()
p.add_argument("--limit", type=int, default=10)
p.add_argument("--active", type=str, default="true")
a = p.parse_args()
key = os.environ.get("STRIPE_SECRET_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "stripe-price-list", "message": "Set STRIPE_SECRET_KEY to enable"})); exit(0)
try:
    params = {"limit": str(a.limit), "active": a.active}
    url = "https://api.stripe.com/v1/prices?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode()})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    prices = [{"id": p["id"], "unit_amount": p["unit_amount"], "currency": p["currency"]} for p in d.get("data", [])]
    print(json.dumps({"ok": True, "tool": "stripe-price-list", "prices": prices, "count": len(prices)}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "stripe-price-list", "error": str(e)}))
