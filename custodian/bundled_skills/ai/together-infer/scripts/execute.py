#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--message", required=True)
p.add_argument("--model", default="meta-llama/Llama-3-8b-chat-hf")
a = p.parse_args()
key = os.environ.get("TOGETHER_API_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "together-infer", "message": "Set TOGETHER_API_KEY to enable"})); exit(0)
try:
    payload = json.dumps({"model": a.model, "messages": [{"role": "user", "content": a.message}], "max_tokens": 512}).encode()
    req = urllib.request.Request("https://api.together.xyz/v1/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "together-infer", "model": a.model, "reply": d["choices"][0]["message"]["content"]}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "together-infer", "error": str(e)}))
