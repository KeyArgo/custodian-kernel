#!/usr/bin/env python3
import argparse, json, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True); p.add_argument("--timeout",type=int,default=10)
    a = p.parse_args()
    try:
        r = requests.get(a.url, timeout=a.timeout, headers={"User-Agent":"custodian/1.0"})
        print(json.dumps({"ok":r.ok,"tool":"http-get","status":r.status_code,"body":r.text[:3000]}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"http-get","error":str(e)}))
if __name__=="__main__": main()
