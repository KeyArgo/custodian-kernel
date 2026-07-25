"""Live smoke test for the deployed getcustodian.xyz site.

Strictly read-only: GET requests and page-load checks only. Never calls
spend/refund/approve/kill/resume/forward_code with real-shaped data --
those are live, publicly-reachable endpoints that move real Stripe
test-mode money and send real Twilio SMS as a side effect (confirmed the
hard way on 2026-07-23: a single diagnostic POST during this suite's
design sent a real SMS). If a future test needs to exercise those routes
end-to-end, it must do so deliberately and visibly, never from an
automated suite that runs unattended.

Hits the real, live domain -- not a local Flask test_client, not static
file parsing. Catches "the deploy is broken" (page 500s, dead link, CDN
serving stale assets) that no other test layer in this repo can see,
since everything else either runs against local source or a local dev
server.

Run with:
    pytest tests/test_live_site_smoke.py -m network -v
Override the target with LIVE_SITE_BASE if testing a preview deploy.
"""
from __future__ import annotations

import os

import pytest

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

BASE = os.environ.get("LIVE_SITE_BASE", "https://getcustodian.xyz").rstrip("/")
TIMEOUT = 15

# Every page a real visitor can navigate to, per the nav's own canonical
# link set (tests/test_pages_frontend_nav_consistency.py) plus the two
# pages that exist but aren't in top nav (checkout, install.sh).
LIVE_PAGES = [
    "/",
    "/console",
    "/operator",
    "/triage",
    "/lie-catch",
    "/guardrails",
    "/paladin",
    "/integrations",
    "/tools",
    "/docs",
    "/checkout",
]

# Read-only API routes safe to hit with zero side effects. Deliberately
# excludes spend/refund/approve/kill/resume/forward_code/reset -- see
# module docstring. spark/status and sandbox/status are GETs but require
# a token live right now (401 is the *expected* passing result, not a
# failure -- this test only asserts "backend answered", not "is public").
READ_ONLY_API_ROUTES = [
    ("/api/v1/operator/pending_code", (200,)),
    ("/api/v1/operator/spark/status", (200, 401)),
    ("/api/v1/operator/sandbox/status", (200, 401)),
    ("/api/v1/hermes/summary", (200,)),
]

pytestmark = pytest.mark.network


def _get(path: str):
    assert requests is not None, "requests must be installed to run live site tests"
    return requests.get(f"{BASE}{path}", timeout=TIMEOUT)


@pytest.mark.parametrize("path", LIVE_PAGES)
def test_page_returns_200(path: str):
    resp = _get(path)
    assert resp.status_code == 200, f"{BASE}{path} returned {resp.status_code}"


@pytest.mark.parametrize("path", LIVE_PAGES)
def test_page_is_real_html_not_an_error_page(path: str):
    """A CDN or Worker misconfiguration can return 200 with an error body
    (a default Cloudflare page, an empty response) -- status code alone
    doesn't prove the real page was served."""
    resp = _get(path)
    body = resp.text
    assert "<html" in body.lower(), f"{BASE}{path}: 200 but body isn't HTML"
    assert "custodian" in body.lower(), f"{BASE}{path}: 200 but body doesn't mention Custodian"
    assert len(body) > 500, f"{BASE}{path}: suspiciously short body ({len(body)} bytes)"


def test_home_page_links_to_every_canonical_page():
    """The live home page's nav must actually contain every canonical
    link, not just the local pages-frontend/index.html source (catches a
    stale/partial deploy where source and live disagree)."""
    body = _get("/").text
    for path in LIVE_PAGES:
        if path in ("/", "/checkout"):
            continue
        assert f'href="{path}"' in body, f"live home page nav is missing a link to {path}"


@pytest.mark.parametrize("path,expected_codes", READ_ONLY_API_ROUTES)
def test_read_only_api_route_responds(path: str, expected_codes: tuple[int, ...]):
    resp = _get(path)
    assert resp.status_code in expected_codes, (
        f"{BASE}{path} returned {resp.status_code}, expected one of {expected_codes}"
    )


def test_static_worker_script_is_served():
    """_worker.js is what actually proxies /api/v1/* to the Flask backend
    -- if Cloudflare Pages ever serves it as a static download instead of
    running it, every API-backed page silently breaks while every static
    page keeps working fine, which the page-level checks above can't see."""
    resp = _get("/api/v1/hermes/summary")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/json"), (
        "expected the Worker to proxy this to Flask and return JSON; "
        f"got content-type={resp.headers.get('content-type')!r} -- "
        "the Worker may not be running at all"
    )


def test_install_script_is_served():
    """Referenced directly in README/docs as a copy-paste install path --
    a 404 here silently breaks onboarding with no other test catching it."""
    resp = _get("/install.sh")
    assert resp.status_code == 200
    assert "custodian" in resp.text.lower()
