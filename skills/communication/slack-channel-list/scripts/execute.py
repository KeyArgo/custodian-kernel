#!/usr/bin/env python3
import argparse, json, os, sys, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--limit", type=int, default=100)
    a = p.parse_args()
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print(json.dumps({"ok": False, "stub": True, "tool": "slack-channel-list", "message": "Set SLACK_BOT_TOKEN to enable."})); return
    try:
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get("https://slack.com/api/conversations.list", headers=headers, params={"limit": a.limit}, timeout=10)
        d = r.json()
        channels = [{"id": c["id"], "name": c["name"]} for c in d.get("channels", [])]
        print(json.dumps({"ok": d.get("ok", False), "tool": "slack-channel-list", "channels": channels}))
    except Exception as e: print(json.dumps({"ok": False, "tool": "slack-channel-list", "error": str(e)}))
if __name__ == "__main__": main()
