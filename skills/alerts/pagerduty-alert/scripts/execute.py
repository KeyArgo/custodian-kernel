#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--summary", required=True)
p.add_argument("--severity", default="error", choices=["critical","error","warning","info"])
p.add_argument("--source", default="custodian-agent")
a = p.parse_args()
key = os.environ.get("PAGERDUTY_API_KEY", "")
if not key:
    print(json.dumps({"ok": False, "stub": True, "tool": "pagerduty-alert", "message": "Set PAGERDUTY_API_KEY to enable"})); exit(0)
try:
    payload = json.dumps({"routing_key": key, "event_action": "trigger",
        "payload": {"summary": a.summary, "severity": a.severity, "source": a.source}}).encode()
    req = urllib.request.Request("https://events.pagerduty.com/v2/enqueue", data=payload,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "pagerduty-alert", "dedup_key": d.get("dedup_key"), "status": d.get("status")}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "pagerduty-alert", "error": str(e)}))
