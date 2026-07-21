"""Regression 2026-07-21: nemo-guide.js and tour-tracker.js still keyed their
per-page logic on '/hermes', the pre-rename Console route (renamed to
/console in commit 817d7b0, with call sites updated in 5599f85). The worker
still 301s /hermes -> /console so links didn't break, but these two
client-side files compare against window.location.pathname directly, which
is only ever '/console' on the live site -- so every '/hermes' check here
was permanently false:
  - nemo-guide.js: EXISTING['/hermes'] was supposed to detect that
    console.html already has its own Nemotron panel and skip creating a
    second one. Since the real path is '/console', the check missed, and
    nemo-guide.js instead built a duplicate floating bubble/panel on top of
    the page's native one.
  - tour-tracker.js: pages.includes('/hermes') in the suggested_next chain
    was always false, so it permanently suggested "go to Console" to
    Nemotron regardless of how far a visitor actually was into the tour.
"""
from pathlib import Path

PAGES_DIR = Path(__file__).resolve().parents[1] / "pages-frontend"


def test_nemo_guide_js_has_no_stale_hermes_route():
    js = (PAGES_DIR / "nemo-guide.js").read_text(encoding="utf-8")
    assert "/hermes" not in js, (
        "nemo-guide.js still references the pre-rename /hermes route -- "
        "this breaks EXISTING[currentPath] duplicate-widget detection on "
        "/console (see module docstring)"
    )
    assert "'/console'" in js, "nemo-guide.js should key its Console-page logic on /console"


def test_tour_tracker_js_has_no_stale_hermes_route():
    js = (PAGES_DIR / "tour-tracker.js").read_text(encoding="utf-8")
    assert "/hermes" not in js, (
        "tour-tracker.js still references the pre-rename /hermes route -- "
        "this permanently breaks the suggested_next chain (see module docstring)"
    )
    assert "'/console'" in js, "tour-tracker.js's TOUR_PAGES should list /console, not /hermes"
