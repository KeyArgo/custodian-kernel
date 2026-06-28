#!/usr/bin/env python3
import argparse, json, os, sys, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--message", required=True); p.add_argument("--username"); p.add_argument("--embeds")
    a = p.parse_args()
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        print(json.dumps({"ok": False, "stub": True, "tool": "discord-webhook", "message": "Set DISCORD_WEBHOOK_URL to enable."})); return
    try:
        payload = {"content": a.message}
        if a.username: payload["username"] = a.username
        if a.embeds: payload["embeds"] = json.loads(a.embeds)
        r = requests.post(url, json=payload, timeout=10)
        print(json.dumps({"ok": r.status_code == 204, "tool": "discord-webhook", "status": r.status_code}))
    except Exception as e: print(json.dumps({"ok": False, "tool": "discord-webhook", "error": str(e)}))
if __name__ == "__main__": main()
