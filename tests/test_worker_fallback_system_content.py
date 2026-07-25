"""Regression test for pages-frontend/_worker.js's FALLBACK_SYSTEM prompt.

Live incident 2026-07-23: Codex Guard and Talaria were added to
FALLBACK_SYSTEM together (see test_worker_nemotron_strip_thinking.py's
docstring for the sibling leak-stripping incident on this same file), but
Paladin -- the credential broker underneath both -- was never added. A
visitor whose request landed on the degraded/OpenRouter fallback lane (the
primary backend proxy fails often enough that this lane is live traffic, not
a rare edge case) and asked about Paladin got told it doesn't exist, even
though it's one of the three shipped, documented products.

No Node needed here: this only checks the prompt text pages-frontend/_worker.js
sends as a literal JS template string, not runtime behavior.
"""
from __future__ import annotations

from pathlib import Path

WORKER_JS = Path(__file__).resolve().parents[1] / "pages-frontend" / "_worker.js"


def _fallback_system_text() -> str:
    text = WORKER_JS.read_text(encoding="utf-8")
    start = text.index("const FALLBACK_SYSTEM")
    end = text.index("`;", start)
    return text[start:end]


def test_fallback_system_knows_paladin():
    fallback_system = _fallback_system_text()
    assert "Paladin" in fallback_system


def test_fallback_system_never_deny_instruction_covers_paladin():
    fallback_system = _fallback_system_text()
    assert "Never deny knowing about" in fallback_system
    never_deny_clause = fallback_system.split("Never deny knowing about", 1)[1]
    assert "Paladin" in never_deny_clause.split(".", 1)[0]
    assert "Codex Guard" in never_deny_clause.split(".", 1)[0]
    assert "Talaria" in never_deny_clause.split(".", 1)[0]
