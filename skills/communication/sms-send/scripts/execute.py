#!/usr/bin/env python3
import argparse, json, os, sys, requests
def main():
    p = argparse.ArgumentParser(); p.add_argument("--to", required=True); p.add_argument("--body", required=True)
    a = p.parse_args()
    sid = os.environ.get("TWILIO_ACCOUNT_SID"); token = os.environ.get("TWILIO_AUTH_TOKEN"); fr = os.environ.get("TWILIO_FROM_NUMBER")
    if not sid or not token or not fr:
        print(json.dumps({"ok": False, "stub": True, "tool": "sms-send", "message": "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER to enable."})); return
    try:
        r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data={"To": a.to, "From": fr, "Body": a.body}, auth=(sid, token), timeout=15)
        d = r.json()
        print(json.dumps({"ok": r.ok, "tool": "sms-send", "sid": d.get("sid"), "status": d.get("status")}))
    except Exception as e: print(json.dumps({"ok": False, "tool": "sms-send", "error": str(e)}))
if __name__ == "__main__": main()
