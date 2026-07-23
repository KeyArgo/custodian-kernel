#!/usr/bin/env python3
import argparse, json, os
ALLOWED = os.environ.get("CUSTODIAN_ALLOWED_WRITE_DIR", "/tmp")
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--path",required=True); p.add_argument("--content",required=True); p.add_argument("--append",action="store_true")
    a = p.parse_args()
    try:
        real = os.path.realpath(a.path)
        allowed_real = os.path.realpath(ALLOWED)
        if real != allowed_real and not real.startswith(allowed_real + os.sep):
            raise PermissionError(f"Path must be under {ALLOWED}")
        mode = "a" if a.append else "w"
        with open(a.path, mode, encoding="utf-8") as f:
            f.write(a.content)
        print(json.dumps({"ok":True,"tool":"file-write","path":a.path,"bytes":len(a.content.encode())}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"file-write","error":str(e)}))
if __name__=="__main__": main()
