#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--message", required=True)
p.add_argument("--model", default="gpt-4o-mini")
p.add_argument("--system", default="You are a helpful assistant.")
a = p.parse_args()
key = os.environ.get("OPENAI_API_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "openai-chat", "message": "Set OPENAI_API_KEY to enable"})); exit(0)
try:
    payload = json.dumps({"model": a.model, "messages": [{"role": "system", "content": a.system}, {"role": "user", "content": a.message}]}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "openai-chat", "model": a.model, "reply": d["choices"][0]["message"]["content"]}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "openai-chat", "error": str(e)}))
