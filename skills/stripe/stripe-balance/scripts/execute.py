#!/usr/bin/env python3
import json, os, requests
key = os.environ.get("STRIPE_SECRET_KEY","")
if not key:
    print(json.dumps({"ok":False,"stub":True,"tool":"stripe-balance","message":"Set STRIPE_SECRET_KEY to enable"}))
else:
    try:
        r = requests.get("https://api.stripe.com/v1/balance", auth=(key,""), timeout=10)
        d = r.json()
        print(json.dumps({"ok":r.ok,"tool":"stripe-balance","available":d.get("available"),"pending":d.get("pending")}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"stripe-balance","error":str(e)}))
