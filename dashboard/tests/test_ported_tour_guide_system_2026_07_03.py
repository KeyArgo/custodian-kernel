"""Regression tests for the cross-page tour-guide system, ported from
hermes-hackathon-2026 (2026-07-03).

custodian-dev's console-equivalent page is /console (console.html).
site-tour.js is page-agnostic and was copied verbatim; tour-tracker.js
and nemo-guide.js hardcode the console route and had every '/console'
occurrence remapped to '/console' (unchanged in custodian-dev).
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read_text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_site_tour_js_exists_and_is_page_agnostic():
    src = read_text("pages-frontend/site-tour.js")
    assert "window.CustodianTour" in src
    assert "/console" not in src, "site-tour.js should never hardcode a page route"


def test_tour_tracker_js_has_no_leftover_console_route():
    src = read_text("pages-frontend/tour-tracker.js")
    assert "'/console'" not in src, "leftover /console route not remapped to /hermes"
    assert "'/hermes'" in src
    # Internal names that merely contain "console" are not routes and must survive.
    assert "ALL_CONSOLE_TABS" in src


def test_nemo_guide_js_has_no_leftover_console_route():
    src = read_text("pages-frontend/nemo-guide.js")
    assert "'/console'" not in src, "leftover /console route not remapped to /hermes"
    assert "'/hermes'" in src
    assert "panelId: 'nemotron-chat-panel'" in src, (
        "nemo-guide.js's EXISTING map must still point at hermes.html's real "
        "chat panel id (verified identical to hermes-hackathon-2026's console.html)"
    )


def test_all_six_pages_include_tour_guide_scripts():
    for page in ("index.html", "console.html", "operator.html", "triage.html",
                 "tools.html", "docs.html"):
        src = read_text(f"pages-frontend/{page}")
        assert 'src="/site-tour.js"' in src, f"{page} missing site-tour.js include"
        assert 'src="/tour-tracker.js"' in src, f"{page} missing tour-tracker.js include"
        assert 'src="/nemo-guide.js"' in src, f"{page} missing nemo-guide.js include"
        # Exactly one of each -- no duplicate includes.
        assert src.count('src="/site-tour.js"') == 1
        assert src.count('src="/tour-tracker.js"') == 1
        assert src.count('src="/nemo-guide.js"') == 1
