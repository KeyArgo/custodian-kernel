#!/usr/bin/env python3
import argparse, json, os, sys, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--title", required=True); p.add_argument("--body", required=True); p.add_argument("--token", required=True)
    a = p.parse_args()
    key = os.environ.get("PUSH_SERVER_KEY")
    if not key:
        print(json.dumps({"ok": False, "stub": True, "tool": "push-notification", "message": "Set PUSH_SERVER_KEY to enable."})); return
    try:
        payload = {"to": a.token, "notification": {"title": a.title, "body": a.body}}
        headers = {"Authorization": f"key={key}", "Content-Type": "application/json"}
        r = requests.post("https://fcm.googleapis.com/fcm/send", json=payload, headers=headers, timeout=10)
        d = r.json()
        print(json.dumps({"ok": d.get("success", 0) > 0, "tool": "push-notification", "message_id": d.get("results", [{}])[0].get("message_id")}))
    except Exception as e: print(json.dumps({"ok": False, "tool": "push-notification", "error": str(e)}))
if __name__ == "__main__": main()
