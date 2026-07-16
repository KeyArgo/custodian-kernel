"""Regression test for the home-page mode-chooser, ported from
hermes-hackathon-2026 (2026-07-03).

Quick walkthrough / Deep dive / Browse freely buttons on the home page,
wired to the shared site-tour.js state added earlier in this session.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read_text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_home_page_has_mode_chooser_buttons():
    src = read_text("pages-frontend/index.html")
    for btn_id in ("tour-mode-quick", "tour-mode-deep", "tour-mode-free", "tour-offer-dismiss"):
        assert f'id="{btn_id}"' in src, f"{btn_id} button missing from home page"
    assert src.count('id="tour-offer"') == 1, "tour-offer container must appear exactly once"


def test_mode_chooser_routes_to_console():
    """The console page is /console.

    This assertion used to be exactly inverted -- it required '/hermes' and
    forbade '/console'. It was ported verbatim from hermes-hackathon-2026 and
    never updated after 817d7b0 renamed the route: hermes.html no longer
    exists, and pages-frontend/_worker.js now 301s /hermes -> /console purely
    so old shared links keep working. The test was asserting the opposite of a
    deliberate design decision, and index.html was right all along.
    """
    src = read_text("pages-frontend/index.html")
    assert "window.location.href = '/console'" in src
    assert "window.location.href = '/hermes'" not in src, \
        "/hermes is a legacy redirect target, not a navigation destination"


def test_mode_chooser_guards_missing_custodian_tour():
    """If site-tour.js hasn't loaded (or fails), the chooser script must no-op
    rather than throw on a null CustodianTour/offer element.
    """
    src = read_text("pages-frontend/index.html")
    assert "if(!window.CustodianTour) return;" in src
    assert "if (!offer) return;" in src
