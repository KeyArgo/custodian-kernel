"""Tests for dashboard/api/debug.py -- client-side error capture.

No test coverage existed for this route before this session's adversarial
review found two real bugs in it: a symlink-following file clobber
(CWE-59) via the fixed, predictable /tmp log path, and unbounded line/col
fields enabling a disk-exhaustion DoS from a single unauthenticated POST.
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dashboard"))

flask = pytest.importorskip("flask")


@pytest.fixture
def client(tmp_path, monkeypatch):
    import dashboard.api.debug as debug_module
    monkeypatch.setattr(debug_module, "LOG_PATH", tmp_path / "errors.jsonl")

    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(debug_module.bp, url_prefix="/api/v1/debug")
    with app.test_client() as c:
        yield c


def test_report_error_then_read_it_back(client):
    r = client.post("/api/v1/debug/report-error", json={
        "message": "TypeError: x is undefined", "stack": "at foo.js:1:1",
        "url": "https://example.com/page", "line": 42, "col": 7,
    })
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    r = client.get("/api/v1/debug/errors")
    errors = r.get_json()["errors"]
    assert len(errors) == 1
    assert errors[0]["message"] == "TypeError: x is undefined"
    assert errors[0]["line"] == "42"


def test_clear_errors(client):
    client.post("/api/v1/debug/report-error", json={"message": "x"})
    client.delete("/api/v1/debug/errors")
    r = client.get("/api/v1/debug/errors")
    assert r.get_json()["errors"] == []


def test_oversized_line_and_col_are_bounded(client):
    """line/col had no length bound at all -- a single unauthenticated POST
    with megabyte-sized values grew the log file by that much, and every
    subsequent write does a full read-modify-rewrite of the file. Found in
    review."""
    r = client.post("/api/v1/debug/report-error", json={
        "message": "x", "line": "A" * 5_000_000, "col": "B" * 5_000_000,
    })
    assert r.status_code == 200

    entries = client.get("/api/v1/debug/errors").get_json()["errors"]
    assert len(entries[0]["line"]) <= 20
    assert len(entries[0]["col"]) <= 20


@pytest.mark.skipif(
    os.name == "nt",
    reason="The symlink refusal relies on O_NOFOLLOW, which does not exist "
    "on Windows (open() there cannot refuse a final-component symlink)",
)
def test_symlinked_log_path_is_refused_not_followed(client, tmp_path):
    """LOG_PATH is a fixed, predictable path in world-writable /tmp shared
    with every other process on the host. A plain read-then-rewrite
    followed a pre-planted symlink transparently, silently merging
    attacker-controlled JSONL into the target file's content and
    eventually overwriting it entirely once MAX_ENTRIES rolled past it
    (CWE-59). Found in review."""
    import dashboard.api.debug as debug_module

    victim = tmp_path / "victim.txt"
    victim.write_text("IMPORTANT VICTIM FILE CONTENT\n")
    log_path = tmp_path / "errors.jsonl"
    log_path.symlink_to(victim)

    r = client.post("/api/v1/debug/report-error", json={"message": "attacker payload"})
    assert r.status_code == 500  # fails closed, does not follow the symlink

    # The victim file must be completely untouched.
    assert victim.read_text() == "IMPORTANT VICTIM FILE CONTENT\n"


def test_reading_through_a_symlinked_log_path_is_also_refused(client, tmp_path):
    """The read side (GET /errors) must not follow a planted symlink either
    -- that would let an attacker who controls the symlink target leak
    arbitrary file content into the error-list response."""
    victim = tmp_path / "secret.txt"
    victim.write_text("not-json-but-still-should-not-be-read\n")
    log_path = tmp_path / "errors.jsonl"
    log_path.symlink_to(victim)

    r = client.get("/api/v1/debug/errors")
    assert r.status_code == 500
