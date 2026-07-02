#!/usr/bin/env python3
"""Execute script for calendar-event-create.

Creates an event in a Google Calendar using the Calendar v3 API. Always
prints a single JSON line on stdout and exits 0. Falls back to a stub
response when GOOGLE_CALENDAR_TOKEN is missing or `requests` is
unavailable.
"""
import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    requests = None

BASE_URL = "https://www.googleapis.com/calendar/v3/calendars"
TOOL = "calendar-event-create"


def _stub(message):
    print(json.dumps({
        "ok": False,
        "stub": True,
        "tool": TOOL,
        "message": message,
    }))


def _ensure_tz(value):
    """If value is a bare date (YYYY-MM-DD) or naive datetime, leave it
    alone — Google Calendar accepts both. Otherwise return value as-is."""
    return value


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--calendar-id", default="primary",
                   help="Calendar ID (default: primary)")
    p.add_argument("--summary", default="", help="Event title")
    p.add_argument("--start", default="", help="Start ISO datetime or date")
    p.add_argument("--end", default="", help="End ISO datetime or date")
    p.add_argument("--description", default="", help="Optional description")
    p.add_argument("--location", default="", help="Optional location")
    p.add_argument("--timezone", default="", help="Optional IANA timezone")
    p.add_argument("--all-day", action="store_true",
                   help="Treat start/end as all-day dates (YYYY-MM-DD)")
    p.add_argument("--timeout", type=int, default=30)
    args = p.parse_args()

    token = os.environ.get("GOOGLE_CALENDAR_TOKEN")
    if not token or requests is None:
        _stub("Set GOOGLE_CALENDAR_TOKEN to enable" if requests is not None
              else "requests library not installed")
        sys.exit(0)

    if not args.summary or not args.start or not args.end:
        print(json.dumps({
            "ok": False,
            "tool": TOOL,
            "error": "--summary, --start and --end are required",
        }))
        sys.exit(0)

    if args.all_day:
        start = {"date": args.start}
        end = {"date": args.end}
    else:
        start = {"dateTime": _ensure_tz(args.start)}
        end = {"dateTime": _ensure_tz(args.end)}
        if args.timezone:
            start["timeZone"] = args.timezone
            end["timeZone"] = args.timezone

    event = {
        "summary": args.summary,
        "start": start,
        "end": end,
    }
    if args.description:
        event["description"] = args.description
    if args.location:
        event["location"] = args.location

    calendar_id = requests.utils.quote(args.calendar_id, safe="")
    url = f"{BASE_URL}/{calendar_id}/events"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        resp = requests.post(
            url,
            headers=headers,
            json=event,
            timeout=args.timeout,
        )
        ok = resp.ok
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        event_id = data.get("id", "") if isinstance(data, dict) else ""
        html_link = data.get("htmlLink", "") if isinstance(data, dict) else ""
        print(json.dumps({
            "ok": ok,
            "tool": TOOL,
            "calendar_id": args.calendar_id,
            "id": event_id,
            "html_link": html_link,
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
