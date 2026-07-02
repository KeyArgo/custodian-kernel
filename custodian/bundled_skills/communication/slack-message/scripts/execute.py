#!/usr/bin/env python3
import argparse, json, os, sys, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--channel", required=True); p.add_argument("--text", required=True); p.add_argument("--blocks")
    a = p.parse_args()
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        print(json.dumps({"ok": False, "stub": True, "tool": "slack-message", "message": "Set SLACK_BOT_TOKEN to enable."})); return
    try:
        payload = {"channel": a.channel, "text": a.text}
        if a.blocks: payload["blocks"] = json.loads(a.blocks)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        r = requests.post("https://slack.com/api/chat.postMessage", json=payload, headers=headers, timeout=10)
        d = r.json()
        print(json.dumps({"ok": d.get("ok", False), "tool": "slack-message", "ts": d.get("ts"), "channel": d.get("channel")}))
    except Exception as e: print(json.dumps({"ok": False, "tool": "slack-message", "error": str(e)}))
if __name__ == "__main__": main()
