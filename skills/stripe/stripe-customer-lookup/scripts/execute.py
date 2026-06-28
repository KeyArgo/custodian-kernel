#!/usr/bin/env python3
import argparse, json, os, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--email"); p.add_argument("--id")
    a = p.parse_args()
    key = os.environ.get("STRIPE_SECRET_KEY","")
    if not key:
        print(json.dumps({"ok":False,"stub":True,"tool":"stripe-customer-lookup","message":"Set STRIPE_SECRET_KEY"})); return
    try:
        if a.id:
            r = requests.get(f"https://api.stripe.com/v1/customers/{a.id}", auth=(key,""), timeout=10)
        else:
            r = requests.get("https://api.stripe.com/v1/customers", auth=(key,""), params={"email":a.email,"limit":1}, timeout=10)
        d = r.json()
        customer = d if a.id else (d.get("data",[{}])[0] if d.get("data") else None)
        print(json.dumps({"ok":r.ok,"tool":"stripe-customer-lookup","customer":customer}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"stripe-customer-lookup","error":str(e)}))
if __name__=="__main__": main()
