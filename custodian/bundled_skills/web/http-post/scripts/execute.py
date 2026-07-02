#!/usr/bin/env python3
import argparse, json, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--payload",default="{}"); p.add_argument("--timeout",type=int,default=10)
    a = p.parse_args()
    try:
        payload = json.loads(a.payload)
        r = requests.post(a.url, json=payload, timeout=a.timeout)
        print(json.dumps({"ok":r.ok,"tool":"http-post","status":r.status_code,"body":r.text[:3000]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"http-post","error":str(e)}))
if __name__=="__main__": main()
