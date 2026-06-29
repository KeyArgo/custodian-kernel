#!/usr/bin/env python3
import argparse, json, os, urllib.request
p = argparse.ArgumentParser()
p.add_argument("--summary", required=True)
p.add_argument("--start", required=True, help="ISO datetime e.g. 2026-07-01T10:00:00")
p.add_argument("--end", required=True, help="ISO datetime")
p.add_argument("--description", default="")
p.add_argument("--calendar-id", default="primary")
a = p.parse_args()
token = os.environ.get("GOOGLE_CALENDAR_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "calendar-create", "message": "Set GOOGLE_CALENDAR_TOKEN to enable"})); exit(0)
try:
    import urllib.parse
    body = json.dumps({"summary": a.summary, "description": a.description,
        "start": {"dateTime": a.start, "timeZone": "UTC"}, "end": {"dateTime": a.end, "timeZone": "UTC"}}).encode()
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(a.calendar_id)}/events"
    req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "calendar-create", "event_id": d["id"], "html_link": d.get("htmlLink")}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "calendar-create", "error": str(e)}))
