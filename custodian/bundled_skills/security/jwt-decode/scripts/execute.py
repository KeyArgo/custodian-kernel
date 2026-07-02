#!/usr/bin/env python3
import argparse, base64, json, sys
p = argparse.ArgumentParser()
p.add_argument("--token", required=True)
a = p.parse_args()
try:
    parts = a.token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a valid JWT (expected 3 parts)")
    def b64decode(s):
        s += "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s)
    header = json.loads(b64decode(parts[0]))
    payload = json.loads(b64decode(parts[1]))
    print(json.dumps({"ok": True, "tool": "jwt-decode", "header": header, "payload": payload,
        "signature_present": bool(parts[2]), "note": "signature not verified — decode only"}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "jwt-decode", "error": str(e)}))
