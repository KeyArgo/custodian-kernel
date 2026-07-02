#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.parse
p = argparse.ArgumentParser()
p.add_argument("--chat-id", required=True)
p.add_argument("--message", required=True)
a = p.parse_args()
token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "telegram-send", "message": "Set TELEGRAM_BOT_TOKEN to enable"})); exit(0)
try:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": a.chat_id, "text": a.message}).encode()
    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": d.get("ok", False), "tool": "telegram-send", "message_id": d.get("result", {}).get("message_id")}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "telegram-send", "error": str(e)}))
