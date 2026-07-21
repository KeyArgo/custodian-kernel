#!/usr/bin/env python3
import argparse, base64, json, os, sys
ALLOWED = os.environ.get("CUSTODIAN_ALLOWED_READ_DIR", "/tmp")
def main():
    p = argparse.ArgumentParser(); p.add_argument("--input"); p.add_argument("--file")
    a = p.parse_args()
    try:
        if a.file:
            # Declared L0 ("read-only, no real-world effects") as a string
            # encode utility -- --file let it read (and exfiltrate, via the
            # returned base64) any file on disk with zero path restriction.
            # Same allowlist boundary as file-read.
            real = os.path.realpath(a.file)
            allowed_real = os.path.realpath(ALLOWED)
            if real != allowed_real and not real.startswith(allowed_real + os.sep):
                raise PermissionError(f"--file must be under {ALLOWED}")
            data = open(a.file,"rb").read()
        else:
            data = (a.input or "").encode()
        print(json.dumps({"ok":True,"tool":"base64-encode","encoded":base64.b64encode(data).decode()}))
    except Exception as e: print(json.dumps({"ok":False,"tool":"base64-encode","error":str(e)}))
if __name__=="__main__": main()
