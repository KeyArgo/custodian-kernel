#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.parse
p = argparse.ArgumentParser()
p.add_argument("--event-id", required=True)
p.add_argument("--calendar-id", default="primary")
a = p.parse_args()
token = os.environ.get("GOOGLE_CALENDAR_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "calendar-delete", "message": "Set GOOGLE_CALENDAR_TOKEN to enable"})); exit(0)
try:
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(a.calendar_id)}/events/{a.event_id}"
    req = urllib.request.Request(url, method="DELETE", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()
    print(json.dumps({"ok": True, "tool": "calendar-delete", "event_id": a.event_id, "deleted": True}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "calendar-delete", "error": str(e)}))
