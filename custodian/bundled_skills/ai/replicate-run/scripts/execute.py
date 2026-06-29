#!/usr/bin/env python3
import argparse, json, os, time, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--model", required=True, help="owner/model:version")
p.add_argument("--input", default="{}", help="JSON input dict")
a = p.parse_args()
token = os.environ.get("REPLICATE_API_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "replicate-run", "message": "Set REPLICATE_API_TOKEN to enable"})); exit(0)
try:
    inp = json.loads(a.input)
    payload = json.dumps({"version": a.model.split(":")[-1] if ":" in a.model else a.model, "input": inp}).encode()
    req = urllib.request.Request("https://api.replicate.com/v1/predictions", data=payload,
        headers={"Authorization": f"Token {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "replicate-run", "prediction_id": d["id"], "status": d["status"], "urls": d.get("urls", {})}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "replicate-run", "error": str(e)}))
