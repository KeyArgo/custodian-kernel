#!/usr/bin/env python3
"""Execute script for calendar-event-list.

Lists events from a Google Calendar using the Calendar v3 API. Always
prints a single JSON line on stdout and exits 0. Falls back to a stub
response when GOOGLE_CALENDAR_TOKEN is missing or `requests` is
unavailable.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    requests = None

BASE_URL = "https://www.googleapis.com/calendar/v3/calendars"
TOOL = "calendar-event-list"


def _stub(message):
    print(json.dumps({
        "ok": False,
        "stub": True,
        "tool": TOOL,
        "message": message,
    }))


def _iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_event(item):
    start = item.get("start", {}) or {}
    return {
        "id": item.get("id", ""),
        "summary": item.get("summary", ""),
        "start": start.get("dateTime") or start.get("date", ""),
        "end": (item.get("end", {}) or {}).get("dateTime")
            or (item.get("end", {}) or {}).get("date", ""),
        "status": item.get("status", ""),
        "htmlLink": item.get("htmlLink", ""),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--calendar-id", default="primary",
                   help="Calendar ID (default: primary)")
    p.add_argument("--max-results", type=int, default=10)
    p.add_argument("--time-min", default="",
                   help="ISO datetime lower bound (default: now)")
    p.add_argument("--time-max", default="",
                   help="Optional ISO datetime upper bound")
    p.add_argument("--q", default="", help="Optional free-text search")
    p.add_argument("--timeout", type=int, default=30)
    args = p.parse_args()

    token = os.environ.get("GOOGLE_CALENDAR_TOKEN")
    if not token or requests is None:
        _stub("Set GOOGLE_CALENDAR_TOKEN to enable" if requests is not None
              else "requests library not installed")
        sys.exit(0)

    time_min = args.time_min or _iso_now()
    calendar_id = requests.utils.quote(args.calendar_id, safe="")
    url = f"{BASE_URL}/{calendar_id}/events"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    params = {
        "maxResults": args.max_results,
        "timeMin": time_min,
        "singleEvents": "true",
        "orderBy": "startTime",
    }
    if args.time_max:
        params["timeMax"] = args.time_max
    if args.q:
        params["q"] = args.q

    try:
        resp = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=args.timeout,
        )
        ok = resp.ok
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        items = data.get("items", []) if isinstance(data, dict) else []
        events = [_coerce_event(it) for it in items]
        print(json.dumps({
            "ok": ok,
            "tool": TOOL,
            "calendar_id": args.calendar_id,
            "events": events,
        }))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "tool": TOOL,
            "calendar_id": args.calendar_id,
            "error": str(e),
        }))


if __name__ == "__main__":
    main()
