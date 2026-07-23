#!/usr/bin/env python3
import argparse, base64, json, os, urllib.request, urllib.parse
from xml.sax.saxutils import escape as _xml_escape
p = argparse.ArgumentParser()
p.add_argument("--to", required=True, help="E.164 phone number")
p.add_argument("--message", required=True)
a = p.parse_args()
sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
token = os.environ.get("TWILIO_AUTH_TOKEN", "")
from_num = os.environ.get("TWILIO_FROM_NUMBER", "")
if not all([sid, token, from_num]):
    print(json.dumps({"ok": False, "stub": True, "tool": "twilio-voice-call",
        "message": "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER to enable"})); exit(0)
try:
    # --message was spliced unescaped into the TwiML document Twilio's server
    # parses as call instructions -- a message containing "</Say><Dial>..."
    # or "<Redirect url=...>" hijacked the entire live call (place additional
    # billed calls, hand call control to an attacker-hosted TwiML URL, record
    # the callee, phish DTMF via <Gather>). This is a text field, not markup;
    # it must never be interpreted as XML.
    twiml = f"<Response><Say>{_xml_escape(a.message)}</Say></Response>"
    body = urllib.parse.urlencode({"To": a.to, "From": from_num, "Twiml": twiml}).encode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
    creds = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req = urllib.request.Request(url, data=body, headers={"Authorization": f"Basic {creds}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "twilio-voice-call", "call_sid": d.get("sid"), "status": d.get("status")}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "twilio-voice-call", "error": str(e)}))
