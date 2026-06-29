#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.parse, base64
p = argparse.ArgumentParser()
p.add_argument("--email", required=True)
p.add_argument("--name", default=None)
p.add_argument("--description", default=None)
a = p.parse_args()
key = os.environ.get("STRIPE_SECRET_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "stripe-customer-create", "message": "Set STRIPE_SECRET_KEY to enable"})); exit(0)
try:
    data = {"email": a.email}
    if a.name: data["name"] = a.name
    if a.description: data["description"] = a.description
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request("https://api.stripe.com/v1/customers", data=body,
        headers={"Authorization": "Basic " + base64.b64encode(f"{key}:".encode()).decode(), "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "stripe-customer-create", "customer_id": d["id"], "email": d["email"]}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "stripe-customer-create", "error": str(e)}))
