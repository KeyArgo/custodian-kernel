#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--message", required=True)
p.add_argument("--model", default="claude-haiku-4-5-20251001")
a = p.parse_args()
key = os.environ.get("ANTHROPIC_API_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "anthropic-chat", "message": "Set ANTHROPIC_API_KEY to enable"})); exit(0)
try:
    payload = json.dumps({"model": a.model, "max_tokens": 1024, "messages": [{"role": "user", "content": a.message}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=payload,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "anthropic-chat", "model": a.model, "reply": d["content"][0]["text"]}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "anthropic-chat", "error": str(e)}))
