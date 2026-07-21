#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.parse
p = argparse.ArgumentParser()
p.add_argument("--event-id", required=True)
p.add_argument("--summary", default=None)
p.add_argument("--start", default=None)
p.add_argument("--end", default=None)
p.add_argument("--calendar-id", default="primary")
a = p.parse_args()
token = os.environ.get("GOOGLE_CALENDAR_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "calendar-update", "message": "Set GOOGLE_CALENDAR_TOKEN to enable"})); exit(0)
try:
    patch = {}
    if a.summary: patch["summary"] = a.summary
    if a.start: patch["start"] = {"dateTime": a.start, "timeZone": "UTC"}
    if a.end: patch["end"] = {"dateTime": a.end, "timeZone": "UTC"}
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(a.calendar_id)}/events/{urllib.parse.quote(a.event_id, safe='')}"
    req = urllib.request.Request(url, data=json.dumps(patch).encode(), method="PATCH",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    print(json.dumps({"ok": True, "tool": "calendar-update", "event_id": d["id"], "updated": d.get("updated")}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "calendar-update", "error": str(e)}))
