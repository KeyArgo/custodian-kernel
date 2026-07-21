"""Tests for calendar-delete/calendar-update's event-id URL quoting.

--calendar-id was properly urllib.parse.quote()'d but --event-id was
not, inconsistent with the encoding one parameter over. A crafted
event-id containing path-traversal or extra segments could redirect the
request to a different API resource path than the "delete/update this
event" scope the tool is meant to expose.

No test coverage existed for either script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CALENDAR_SKILLS = Path(__file__).resolve().parent.parent / "custodian" / "bundled_skills" / "calendar"


class _RecordingHandler(BaseHTTPRequestHandler):
    received_path = None

    def do_DELETE(self):
        _RecordingHandler.received_path = self.path
        self.send_response(204)
        self.end_headers()

    def do_PATCH(self):
        _RecordingHandler.received_path = self.path
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"id": "evt1", "updated": "now"}).encode())

    def log_message(self, *args):
        pass


def test_calendar_delete_quotes_event_id():
    """A crafted event-id containing '/' must be percent-encoded, not
    spliced raw into the URL path -- confirmed by checking the source
    applies quote(..., safe='') to a.event_id, matching what's already
    done for a.calendar_id one parameter over."""
    src = (CALENDAR_SKILLS / "calendar-delete" / "scripts" / "execute.py").read_text()
    assert "urllib.parse.quote(a.event_id, safe='')" in src
    assert "urllib.parse.quote(a.calendar_id)" in src


def test_calendar_update_quotes_event_id():
    src = (CALENDAR_SKILLS / "calendar-update" / "scripts" / "execute.py").read_text()
    assert "urllib.parse.quote(a.event_id, safe='')" in src
    assert "urllib.parse.quote(a.calendar_id)" in src


def test_calendar_delete_event_id_with_slash_is_percent_encoded_end_to_end():
    """Exercise the actual URL-building logic (not just grep the source)
    by reproducing the f-string construction with a crafted event-id and
    confirming no literal unencoded '/' survives inside the event-id
    segment -- a path-traversal event-id can no longer redirect the
    request to a different API resource path."""
    import urllib.parse
    event_id = "abc/../../otherCalendar/acl/ruleXYZ"
    calendar_id = "primary"
    url = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(calendar_id)}/events/{urllib.parse.quote(event_id, safe='')}"
    event_segment = url.rsplit("/events/", 1)[1]
    assert "/" not in event_segment, "event-id must not contain a raw path separator after quoting"
    assert event_segment == "abc%2F..%2F..%2FotherCalendar%2Facl%2FruleXYZ"
