#!/usr/bin/env python3
import argparse, json
from urllib.parse import urlparse, parse_qs
def main():
    p = argparse.ArgumentParser(); p.add_argument("--url",required=True)
    a = p.parse_args()
    try:
        r = urlparse(a.url)
        print(json.dumps({"ok":True,"tool":"url-parse","scheme":r.scheme,"host":r.netloc,"path":r.path,"query":parse_qs(r.query),"fragment":r.fragment}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"url-parse","error":str(e)}))
if __name__=="__main__": main()
