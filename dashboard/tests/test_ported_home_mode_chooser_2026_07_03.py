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


def test_mode_chooser_routes_to_hermes_not_console():
    """This repo's console-equivalent page is /hermes, not /console."""
    src = read_text("pages-frontend/index.html")
    assert "window.location.href = '/hermes'" in src
    assert "window.location.href = '/console'" not in src


def test_mode_chooser_guards_missing_custodian_tour():
    """If site-tour.js hasn't loaded (or fails), the chooser script must no-op
    rather than throw on a null CustodianTour/offer element.
    """
    src = read_text("pages-frontend/index.html")
    assert "if(!window.CustodianTour) return;" in src
    assert "if (!offer) return;" in src
