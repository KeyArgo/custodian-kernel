"""Regression tests for judge-facing public page routes.

These assert the renamed public Console route stays available anywhere the
Flask app is serving pages directly, not just through Cloudflare Pages.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dashboard/, for `import app`


@pytest.fixture
def client():
    from app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_console_route_serves_live_dashboard(client):
    response = client.get("/console")

    assert response.status_code == 200
    assert b"Custodian" in response.data
    assert b"/api/v1/hermes/summary" in response.data
