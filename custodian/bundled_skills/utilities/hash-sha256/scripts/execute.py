#!/usr/bin/env python3
import argparse, hashlib, json
def main():
    p = argparse.ArgumentParser(); p.add_argument("--input"); p.add_argument("--file")
    a = p.parse_args()
    try:
        data = open(a.file,"rb").read() if a.file else (a.input or "").encode()
        h = hashlib.sha256(data).hexdigest()
        print(json.dumps({"ok":True,"tool":"hash-sha256","hash":h}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"hash-sha256","error":str(e)}))
if __name__=="__main__": main()
