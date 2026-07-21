"""Tests for webhook-post's destination validation.

Declared L1 (autonomous, no human approval), with zero destination
validation on a caller-supplied --url despite the SKILL.md description
implying a "configured" endpoint set. Any caller could reach internal-only
services or the cloud metadata endpoint. Fixed by blocking private/
loopback/link-local/reserved ranges, matching the same fix applied to
http-get/http-post/web-scrape.

No test coverage existed for this script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "bundled_skills" / "communication" / "webhook-post" / "scripts" / "execute.py"
)


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"received": True}).encode())

    def log_message(self, *args):
        pass


def _run(args: list) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
    )
    return json.loads(result.stdout)


def test_blocks_loopback_destination():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        out = _run(["--url", f"http://127.0.0.1:{port}/hook"])
        assert out["ok"] is False
        assert "destination not allowed" in out["error"]
    finally:
        server.shutdown()


def test_blocks_cloud_metadata_literal():
    out = _run(["--url", "http://169.254.169.254/latest/meta-data/"])
    assert out["ok"] is False
    assert "destination not allowed" in out["error"]


def test_blocks_disallowed_scheme():
    out = _run(["--url", "file:///etc/passwd"])
    assert out["ok"] is False
    assert "scheme not allowed" in out["error"]


def test_does_not_follow_redirects():
    src = SCRIPT.read_text()
    assert "allow_redirects=False" in src
