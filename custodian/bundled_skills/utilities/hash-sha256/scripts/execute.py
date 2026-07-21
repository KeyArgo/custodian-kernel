#!/usr/bin/env python3
import argparse, hashlib, json, os
ALLOWED = os.environ.get("CUSTODIAN_ALLOWED_READ_DIR", "/tmp")
def main():
    p = argparse.ArgumentParser(); p.add_argument("--input"); p.add_argument("--file")
    a = p.parse_args()
    try:
        if a.file:
            # Declared L0 ("read-only, no real-world effects") as a hash
            # utility -- --file let it fingerprint (and confirm the exact
            # content of, via hash comparison against a known value) any
            # file on disk with zero path restriction. Same allowlist
            # boundary as file-read.
            real = os.path.realpath(a.file)
            allowed_real = os.path.realpath(ALLOWED)
            if real != allowed_real and not real.startswith(allowed_real + os.sep):
                raise PermissionError(f"--file must be under {ALLOWED}")
            data = open(a.file,"rb").read()
        else:
            data = (a.input or "").encode()
        h = hashlib.sha256(data).hexdigest()
        print(json.dumps({"ok":True,"tool":"hash-sha256","hash":h}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"hash-sha256","error":str(e)}))
if __name__=="__main__": main()
