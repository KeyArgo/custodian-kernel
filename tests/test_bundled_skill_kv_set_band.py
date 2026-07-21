"""Test for kv-set's declared trust band.

kv-set's SKILL.md declared band L0 ("read-only, no real-world effects")
while the script performs a real, persistent write (INSERT OR REPLACE) to
the KV store's SQLite file -- inconsistent with its sibling kv-delete
(also a mutation), correctly declared L1.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SKILL_MD = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "bundled_skills" / "memory" / "kv-set" / "SKILL.md"
)


def _frontmatter() -> dict:
    text = SKILL_MD.read_text()
    _, fm, _ = text.split("---", 2)
    return yaml.safe_load(fm)


def test_kv_set_band_matches_its_actual_mutating_effect():
    meta = _frontmatter()
    band = meta["metadata"]["custodian"]["band"]
    assert band != "L0", "kv-set writes to persistent storage -- L0 (read-only) misdeclares it"
    assert band == "L1", "should match its sibling kv-delete's band for the same mutation class"


def test_kv_set_prose_matches_its_declared_band():
    text = SKILL_MD.read_text()
    assert "Read-only; no real-world effects" not in text
    assert "L1** authority" in text
