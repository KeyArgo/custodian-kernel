"""Regression tests for the HR/Finance/IT/Legal triage department packs,
ported from hermes-hackathon-2026 (2026-07-03).

These are frontend-only demo packs (no dedicated backend pack module) —
each submits free text through the existing /api/v1/triage/custom endpoint,
tagged with a real backend pack (purchasing/refunds/cloud) so the kernel
evaluates the claim against an actual sandbox. Source-inspection style,
matching this repo's existing pattern for frontend regression coverage.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read_text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_all_four_department_packs_have_tabs_and_sections():
    src = read_text("pages-frontend/triage.html")
    for pack in ("hr", "finance", "it", "legal"):
        assert f'data-pack="{pack}"' in src, f"{pack} pack tab missing"
        assert f'id="pack-{pack}"' in src, f"{pack} pack section missing"
        assert f'id="{pack}-cases"' in src, f"{pack} cases mount missing"


def test_all_four_department_packs_have_scenario_metadata():
    src = read_text("pages-frontend/triage.html")
    m = re.search(r"const SCENARIO_META = \{(.*?)\n\};", src, re.DOTALL)
    assert m, "SCENARIO_META not found"
    body = m.group(1)
    for pack in ("hr:", "finance:", "it:", "legal:"):
        assert pack in body, f"SCENARIO_META missing {pack.rstrip(':')}"


def test_department_packs_map_to_real_backend_packs():
    """hr/finance/it/legal have no backend pack module of their own -- each
    must declare a backendPack that IS a real, registered pack (refunds,
    purchasing, or cloud) so /custom evaluates against a real sandbox
    instead of silently falling through to the default.
    """
    src = read_text("pages-frontend/triage.html")
    m = re.search(r"const CUSTOM_BOX = \{(.*?)\n\};", src, re.DOTALL)
    assert m, "CUSTOM_BOX not found"
    body = m.group(1)
    real_packs = {"refunds", "purchasing", "cloud"}
    for pack in ("hr", "finance", "it", "legal"):
        entry_m = re.search(pack + r":\s*\{(.*?)\n  \},", body, re.DOTALL)
        assert entry_m, f"{pack} entry not found in CUSTOM_BOX"
        bp_m = re.search(r"backendPack:\s*'(\w+)'", entry_m.group(1))
        assert bp_m, f"{pack} has no backendPack"
        assert bp_m.group(1) in real_packs, (
            f"{pack}.backendPack={bp_m.group(1)!r} is not a real registered pack"
        )


def test_run_custom_routes_backend_pack_entries_through_free_text_path():
    """Any CUSTOM_BOX entry with a backendPack (refunds, or the frontend-only
    hr/finance/it/legal packs) must go through the free-text /custom POST,
    not the fixed-case GET path meant for purchasing/cloud.
    """
    src = read_text("pages-frontend/triage.html")
    m = re.search(r"async function runCustom\(\).*?\n\}", src, re.DOTALL)
    assert m, "runCustom not found"
    body = m.group(0)
    assert "box.backendPack" in body
    assert "pack: box.backendPack || currentPack" in body
