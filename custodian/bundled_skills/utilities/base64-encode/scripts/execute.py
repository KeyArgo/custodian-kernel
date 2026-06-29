#!/usr/bin/env python3
import argparse, base64, json, sys
def main():
    p = argparse.ArgumentParser(); p.add_argument("--input"); p.add_argument("--file")
    a = p.parse_args()
    try:
        data = open(a.file,"rb").read() if a.file else (a.input or "").encode()
        print(json.dumps({"ok":True,"tool":"base64-encode","encoded":base64.b64encode(data).decode()}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"base64-encode","error":str(e)}))
if __name__=="__main__": main()
