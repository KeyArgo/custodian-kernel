#!/usr/bin/env python3
import argparse, json, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--payload",default="{}"); p.add_argument("--headers",default="{}")
    a = p.parse_args()
    try:
        payload = json.loads(a.payload); headers = json.loads(a.headers) or {"Content-Type":"application/json"}
        r = requests.post(a.url, json=payload, headers=headers, timeout=10)
        print(json.dumps({"ok":r.ok,"tool":"webhook-post","status":r.status_code,"body":r.text[:500]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"webhook-post","error":str(e)}))
if __name__=="__main__": main()
