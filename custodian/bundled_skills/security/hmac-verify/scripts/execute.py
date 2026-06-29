#!/usr/bin/env python3
import argparse, hashlib, hmac, json
p = argparse.ArgumentParser()
p.add_argument("--secret", required=True)
p.add_argument("--message", required=True)
p.add_argument("--signature", required=True)
p.add_argument("--algorithm", default="sha256")
a = p.parse_args()
try:
    algo = getattr(hashlib, a.algorithm, None)
    if not algo:
        raise ValueError(f"Unknown algorithm: {a.algorithm}")
    expected = hmac.new(a.secret.encode(), a.message.encode(), algo).hexdigest()
    sig = a.signature.lstrip("sha256=").lstrip("sha1=")
    valid = hmac.compare_digest(expected, sig)
    print(json.dumps({"ok": True, "tool": "hmac-verify", "valid": valid,
        "algorithm": a.algorithm, "expected": expected}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "hmac-verify", "error": str(e)}))
