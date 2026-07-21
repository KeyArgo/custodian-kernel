"""Regression tests for the Cloudflare Worker's own leak-stripping port.

Bug report 2026-07-19 (fork audit, confirmed): dashboard/api/nemotron_chat.py's
_strip_thinking() went through ten rounds of fixes for real leaked-reasoning
shapes (numbered self-talk, quoted drafts tallying their own word count,
untagged deliberation with no <think> markers -- see
dashboard/tests/test_nemotron_strip_thinking.py). None of that applied to
pages-frontend/_worker.js's nemotronDirectFallback(), which is the path that
actually served the leak reported this session: the file's own comments
document the primary backend proxy failing "~20-50%" of single attempts, at
which point the Worker calls OpenRouter directly from the edge and used to
sanitize with only `.replace(/<think>.../, '')` -- catching nothing else.

nemoStripThinking() in _worker.js is a JS port of the same line-classification
mechanism (not a byte-for-byte port of every historical Python edge case).
These tests run the REAL function extracted from _worker.js via Node, not a
reimplementation in this test file, so they catch actual drift between the
two -- the same failure mode test_skill_trees_in_sync.py guards against for
the Python skill trees.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WORKER_JS = Path(__file__).resolve().parents[1] / "pages-frontend" / "_worker.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not available in this environment"
)

_RUNNER_TEMPLATE = """
{snippet}
let input = '';
process.stdin.on('data', c => input += c);
process.stdin.on('end', () => {{
  const data = JSON.parse(input);
  process.stdout.write(JSON.stringify({{ result: nemoStripThinking(data.text) }}));
}});
"""


def _extract_snippet() -> str:
    src = WORKER_JS.read_text(encoding="utf-8")
    start = src.index("const NEMO_META_LINE_RE")
    end = src.index("async function nemotronDirectFallback")
    return src[start:end]


def _strip_via_worker(text: str) -> str:
    runner = _RUNNER_TEMPLATE.format(snippet=_extract_snippet())
    proc = subprocess.run(
        ["node", "--input-type=commonjs", "-e", runner],
        input=json.dumps({"text": text}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"node runner failed: {proc.stderr}"
    return json.loads(proc.stdout)["result"]


def test_worker_strips_live_2026_07_19_second_capture_leak():
    """The actual leak a visitor saw this session -- see
    dashboard/tests/test_nemotron_strip_thinking.py's twin of this test for
    the full annotated capture. If the Worker's fallback fires under this
    exact leak shape, none of it should reach the visitor except the one
    clean quoted draft the Python-side Strategy 2 equivalent recovers."""
    leaked = (
        "We need to respond with 2-3 sentences: who I am and what this "
        "dashboard watches. Then tell them the most important thing is to "
        "try the live demo themselves — include the operator panel as a "
        "clickable link right in the body. Mention the audit feed as "
        "secondary. End with 2-3  chips.\n"
        "\n"
        "We need to keep under 120 words. Let's craft ~70 words.\n"
        "\n"
        "Sentences:\n"
        "\n"
        "1. I'm Nemotron 3 Super, the reasoning model that reads customer "
        "messages and proposes a fair disposition. 2. This dashboard "
        "watches the claim extraction, suggested actions, and the live "
        "audit feed that records every enforcement decision.\n"
        "\n"
        "Then: The most important thing is to jump in and try the live "
        "demo yourself — just click the operator panel to run the full "
        "flow with real Stripe money and SMS codes. (audit feed is "
        "secondary but still fun to watch.)\n"
        "\n"
        "Then end with chips: , , .\n"
        "\n"
        "Let's count words roughly.\n"
        "\n"
        "\"I'm Nemotron 3 Super, the reasoning model that reads customer "
        "messages and proposes a fair disposition.\" (maybe 14 words)\n"
        "\"This dashboard watches the claim extraction, suggested actions, "
        "and the live audit feed that records every enforcement decision.\" "
        "(~18 words)\n"
        "\"The most important thing is to jump in and try the live demo "
        "yourself — just click the operator panel to run the full flow "
        "with real Stripe money and SMS codes.\" (~27 words)\n"
        "\"(audit feed is secondary but still fun to watch.)\" (~6 words)\n"
        "\n"
        "Total words maybe ~70. Under 120."
    )
    result = _strip_via_worker(leaked)
    for leak_marker in (
        "We need to", "Sentences:", "1. I'm Nemotron", "Then:",
        "Let's count", "(maybe 14 words)", "(~18 words)",
        "Total words maybe",
    ):
        assert leak_marker not in result, f"leaked fragment {leak_marker!r} in {result!r}"
    assert result, "expected the quoted-draft fallback to recover something usable"


def test_worker_returns_empty_for_pure_preamble_leak():
    leaked = (
        "We need to respond in 2-3 sentences: who we are and what dashboard watches.\n"
        "Then tell them the most important thing is to try the live demo themselves.\n"
        "Mention audit feed as secondary.\n"
        "End with 2-3 chips.\n"
        "Make sure no bullet list, no raw field names.\n"
        "Use plain language. Keep under 120 words.\n"
        "So produce maybe 2 sentences?"
    )
    assert _strip_via_worker(leaked) == ""


def test_worker_keeps_a_clean_answer_untouched():
    clean = (
        "I'm Nemotron 3 Super, the intelligence layer that reads customer "
        "requests. This dashboard watches the live audit feed and kernel "
        "decisions. Try the operator panel to run the full demo yourself."
    )
    assert _strip_via_worker(clean) == clean


def test_worker_strips_think_tags():
    text = "<think>internal reasoning here</think>The real answer."
    assert _strip_via_worker(text) == "The real answer."


def test_worker_strips_same_line_selfcount_leak():
    """Live leak 2026-07-21: a visitor on the Tools page saw the fallback
    lane's raw deliberation because the whole thing was ONE unbroken line
    (no newlines at all) -- nemoIsMetaLine only ever classified whole
    LINES, so a giant single line sailed through untouched. This is the
    exact v7 shape dashboard/api/nemotron_chat.py's _strip_thinking() fixed
    on 2026-07-04 (token-level self-count-run + tally detection, not
    line-level) -- the Worker's port never carried that fix until now.

    dashboard/tests/test_nemotron_strip_thinking.py's Python
    _strip_thinking() reduces this exact captured text to '' (the "Count:"
    prefix before the self-talk doesn't end in sentence punctuation, so the
    fail-closed guard blanks it). The Worker port must match."""
    leaked = (
        "Count: You've(1) walked2 through3 the4 demo5 flow6 and7 the8 "
        "Operator9 panel;10 now11 the12 Tools13 page14 shows15 the16 "
        "individual17 pieces — claim18 extractor,19 disposition20 engine,21 "
        "and22 sandbox23 logger — you24 can25 tweak26 each27 to28 see29 "
        "how30 they31 shape32 the33 final34 decision35. 35 words, under 50. "
        "Good. No re-introduction. No JSON. Friendly. No self-aware robot "
        "humor? Could add a light joke. Maybe add \" (no soldering "
        "required)\". But that adds words. Let's see if we can add a bit "
        "of humor while staying under 50. Add \" (no soldering required)\" "
        "at end. That adds words: no(36) soldering(37) required(38) . "
        "Actually parentheses count as separate? We'll count words: "
        "\"no\"(36) \"soldering\"(37) \"required\"(38). So total 38 words. "
        "Still under 50. Let's rewrite sentence: \"You've walked through "
        "the demo flow and the Operator panel; now the Tools page shows "
        "the individual pieces — claim extractor, disposition engine, and "
        "sandbox logger — you can tweak each to see how they shape the "
        "final decision (no soldering required).\""
    )
    result = _strip_via_worker(leaked)
    assert result == "", f"expected fail-closed empty string, got {result!r}"


def test_worker_strips_word_count_suffix_keeps_good_prefix():
    """Live leak 2026-07-21 (Integrations page): a genuinely good answer was
    followed, on the same line, by a decorative emoji and then a literal
    "(Word count: 98)" tally -- no marker anywhere matched this shape (every
    existing one requires the number BEFORE "words", not after "count:"), so
    the whole trailing artifact reached the visitor. Unlike the pure-leak
    tests above, this one has a real, complete answer that must survive --
    only the emoji + tally suffix should be trimmed."""
    leaked = (
        "I'm Nemotron 3 Super, focused on understanding your messy messages "
        "and turning them into clear actions for the Custodian sandbox. I "
        "don't have details on \"Codex Guard\" or \"Talaria\" – those "
        "aren't part of *this* demo's visible layers (my role, the "
        "enforcement box, or the Operator panel). My world is refunds, "
        "complaints, and invoices right now.  \n"
        "For hands-on exploration with real Stripe tests and SMS codes, "
        "swing by the Operator page (`/operator`). It’s where you "
        "steer the demo yourself – I’ll be here interpreting the "
        "notes you leave! \U0001F604 (Word count: 98)"
    )
    result = _strip_via_worker(leaked)
    assert "Word count" in leaked  # sanity: the fixture actually has the leak
    assert "Word count" not in result
    assert result.endswith("you leave!"), repr(result)
