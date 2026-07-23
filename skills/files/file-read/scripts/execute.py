#!/usr/bin/env python3
import argparse, json, os
ALLOWED = os.environ.get("CUSTODIAN_ALLOWED_READ_DIR", "/tmp")
def main():
    p = argparse.ArgumentParser(); p.add_argument("--path",required=True); p.add_argument("--limit",type=int,default=500)
    a = p.parse_args()
    try:
        real = os.path.realpath(a.path)
        allowed_real = os.path.realpath(ALLOWED)
        if real != allowed_real and not real.startswith(allowed_real + os.sep):
            raise PermissionError(f"Path must be under {ALLOWED}")
        with open(a.path,"r",encoding="utf-8",errors="replace") as f:
            lines = f.readlines()[:a.limit]
        content = "".join(lines)
        print(json.dumps({"ok":True,"tool":"file-read","path":a.path,"content":content,"lines":len(lines)}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"file-read","error":str(e)}))
if __name__=="__main__": main()
