#!/usr/bin/env python3
import argparse, json, os, urllib.request, urllib.parse
p = argparse.ArgumentParser()
p.add_argument("--max-results", type=int, default=10)
p.add_argument("--calendar-id", default="primary")
a = p.parse_args()
token = os.environ.get("GOOGLE_CALENDAR_TOKEN", "")
if not token:
    print(json.dumps({"ok": False, "stub": True, "tool": "calendar-list", "message": "Set GOOGLE_CALENDAR_TOKEN to enable"})); exit(0)
try:
    params = urllib.parse.urlencode({"maxResults": a.max_results, "singleEvents": "true", "orderBy": "startTime",
        "timeMin": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")})
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(a.calendar_id)}/events?{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    events = [{"id": e["id"], "summary": e.get("summary", ""), "start": e["start"].get("dateTime", e["start"].get("date"))} for e in d.get("items", [])]
    print(json.dumps({"ok": True, "tool": "calendar-list", "events": events, "count": len(events)}))
except Exception as e:
    print(json.dumps({"ok": False, "tool": "calendar-list", "error": str(e)}))
