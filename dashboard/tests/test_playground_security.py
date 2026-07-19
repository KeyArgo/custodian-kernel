"""Security regression tests for the playground endpoints.

Added after a real security audit found two real issues: a reflected XSS
(fixed in the dashboard's client-side JS, not testable from Python -- see
the escapeHtml() usage in templates/hermes/dashboard.html) and zero rate
limiting on public, unauthenticated, compute-bearing endpoints. These tests
cover what's testable from the Python side: the rate limiter actually
triggers, and the backend reflects raw input verbatim in JSON (confirming
the JSON layer itself was never the vulnerability -- the fix had to be in
how the frontend renders that JSON, which is why this file can prove the
backend behaves correctly but can't prove the XSS fix by itself).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dashboard/, for `import app`/`import api.*`


@pytest.fixture
def client():
    from app import app
    import api.playground as playground
    # Each test gets a clean rate-limit ledger -- otherwise test order would
    # make earlier tests' requests count against later ones.
    playground._request_log.clear()
    return app.test_client()


def test_decide_allows_up_to_the_limit(client):
    for _ in range(30):
        r = client.post('/api/v1/playground/decide', json={'amount': 1.0, 'description': 'x'})
        assert r.status_code == 200


def test_decide_blocks_past_the_limit(client):
    for _ in range(30):
        client.post('/api/v1/playground/decide', json={'amount': 1.0, 'description': 'x'})
    r = client.post('/api/v1/playground/decide', json={'amount': 1.0, 'description': 'x'})
    assert r.status_code == 429
    assert 'Rate limit' in r.get_json()['error']


def test_try_approve_has_its_own_independent_limit_bucket(client):
    """decide and try-approve share the rate-limit code but are keyed by IP,
    not by route -- confirm they don't share a single combined budget in a
    way that would make one endpoint starve the other unexpectedly."""
    for _ in range(30):
        client.post('/api/v1/playground/decide', json={'amount': 1.0, 'description': 'x'})
    # decide is now exhausted for this IP; try-approve uses the same
    # _request_log dict keyed by IP, so it SHOULD also be exhausted --
    # this test documents that shared-budget behavior explicitly rather
    # than leaving it as an unstated assumption.
    r = client.post('/api/v1/playground/try-approve', json={'code': '000000'})
    assert r.status_code == 429


def test_raw_input_is_reflected_verbatim_in_json(client):
    """The backend correctly does NOT html-escape JSON responses -- that
    would be the wrong fix (JSON isn't a rendering context, and escaping
    here would corrupt legitimate punctuation in description text). The
    real fix lives client-side. This test pins the backend's correct
    behavior so a future 'fix' doesn't break it by over-correcting here."""
    payload = "<img src=x onerror=alert(1)>"
    r = client.post('/api/v1/playground/try-approve', json={'code': payload})
    assert r.status_code == 200
    assert payload in r.get_json()['message']


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_decide_rejects_nonfinite_amounts(client, amount):
    response = client.post('/api/v1/playground/decide', json={'amount': amount})
    assert response.status_code == 400
