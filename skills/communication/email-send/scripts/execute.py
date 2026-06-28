#!/usr/bin/env python3
import argparse, json, os, sys, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--to", required=True); p.add_argument("--from-email", dest="from_email", required=True); p.add_argument("--subject", required=True); p.add_argument("--body", required=True); p.add_argument("--html", action="store_true")
    a = p.parse_args()
    key = os.environ.get("SENDGRID_API_KEY")
    if not key:
        print(json.dumps({"ok": False, "stub": True, "tool": "email-send", "message": "Set SENDGRID_API_KEY to enable."})); return
    try:
        content = [{"type": "text/html" if a.html else "text/plain", "value": a.body}]
        payload = {"personalizations": [{"to": [{"email": a.to}]}], "from": {"email": a.from_email}, "subject": a.subject, "content": content}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        r = requests.post("https://api.sendgrid.com/v3/mail/send", json=payload, headers=headers, timeout=15)
        print(json.dumps({"ok": r.status_code == 202, "tool": "email-send", "status": r.status_code}))
    except Exception as e: print(json.dumps({"ok": False, "tool": "email-send", "error": str(e)}))
if __name__ == "__main__": main()
