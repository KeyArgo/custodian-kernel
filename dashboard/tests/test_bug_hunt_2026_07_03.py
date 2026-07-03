"""Regression test for bug-hunt fix 2026-07-03.

Pure source-code inspection — no live API calls, no model invocations.

Bug: `custodian.inference.router.NemoClawRouter._strip_thinking` only strips
`<think>...</think>` tags. It knows nothing about the meta-instruction
preamble pattern ("We need to respond with...", "Must not mention...") that
`dashboard/api/nemotron_chat.py`'s own `_strip_thinking` (v5) was built to
catch. Because the primary inference path in `ask()` calls
`_nemo_client.complete(...)` (NemoClawRouter) directly and used its return
value unfiltered, a degenerate response that never escapes the model's
self-talk was returned straight to the visitor as the "answer" instead of
being treated as a failure and falling back to OpenRouter/NIM direct.

Live-reproduced 2026-07-03: two live requests to the production /ask
endpoint returned hundreds of words of "Must not mention ..." repetition
as the visible answer, and a third request timed out entirely (surfaced to
the visitor as "Backend unavailable -- both nodes unreachable") because the
model burned its full max_tokens budget on the same self-talk loop instead
of ever producing a real answer quickly.

Fix: apply nemotron_chat.py's own `_strip_thinking` to the NemoClawRouter
result too, and treat an empty result as a failure (fall through to the
next endpoint) instead of returning '' to the visitor.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read_text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_nemoclaw_router_result_is_passed_through_strip_thinking():
    """The `_nemo_client.complete(...)` call's result must be passed through
    this module's own `_strip_thinking` before being used as the answer --
    NemoClawRouter's internal stripper only removes <think> tags and misses
    the meta-instruction preamble pattern.
    """
    src = read_text("dashboard/api/nemotron_chat.py")
    m = re.search(
        r"answer\s*=\s*_nemo_client\.complete\(.*?\n\s+\)\s*\n(.*?)except RuntimeError:",
        src, re.DOTALL,
    )
    assert m, "_nemo_client.complete() call block not found"
    post_call = m.group(1)
    assert re.search(r"answer\s*=\s*_strip_thinking\(answer\)", post_call), (
        "_nemo_client.complete() result must be run through _strip_thinking "
        "before use -- NemoClawRouter's own stripper doesn't catch the "
        "meta-instruction preamble pattern"
    )


def test_nemoclaw_router_empty_stripped_answer_falls_back():
    """If _strip_thinking reduces the router's answer to '', that must be
    treated as a failure (answer = None) so the OpenRouter/NIM fallback
    paths run, instead of returning an empty string straight to the visitor.
    """
    src = read_text("dashboard/api/nemotron_chat.py")
    m = re.search(
        r"answer\s*=\s*_strip_thinking\(answer\)\s*\n\s+if not answer:\s*\n\s+answer\s*=\s*None",
        src,
    )
    assert m, (
        "an empty result from _strip_thinking(answer) on the NemoClawRouter "
        "path must reset answer to None so the fallback chain runs"
    )


# ── nemo-guide.js minimize-persistence bug (bug-hunt 2026-07-03) ────────────
#
# Reported live: minimizing the Nemotron widget did not stick -- navigating
# to another page (or back to the same page) made it pop open again.
#
# Root cause: operator.html/triage.html/console.html all read and write a
# single shared `assistant_dismissed` flag (site-tour.js) so a minimize on
# any one of them is honored on the others. But nemo-guide.js (the widget
# used on Home/Tools/Docs) never wrote that shared flag on close, AND
# unconditionally reset it to `false` on every navigation -- silently
# undoing a minimize done on operator.html/triage.html/console.html the
# moment the visitor arrived at Home/Tools/Docs.

def test_nemo_guide_does_not_force_reset_shared_dismissed_flag_on_navigation():
    """nemo-guide.js must not unconditionally clear assistant_dismissed (or
    its own per-page dismissed map) just because the visitor navigated --
    that defeats the whole point of a persistent minimize.
    """
    src = read_text("pages-frontend/nemo-guide.js")
    m = re.search(r"if \(_navigated\) \{(.*?)\n  \}", src, re.DOTALL)
    assert m, "_navigated block not found"
    body = m.group(1)
    assert "assistant_dismissed = false" not in body, (
        "nemo-guide.js must not force assistant_dismissed back to false on "
        "navigation -- that undoes a minimize done on any page"
    )
    assert "delete gs.dismissed[currentPath]" not in body, (
        "nemo-guide.js must not clear its own per-page dismissed flag on "
        "navigation -- that undoes a minimize on this page"
    )


def test_nemo_guide_close_panel_sets_shared_dismissed_flag():
    """closePanel() must call CustodianTour.dismissAssistant() so a minimize
    on Home/Tools/Docs is honored by operator.html/triage.html/console.html
    too (they all gate auto-open on this shared flag).
    """
    src = read_text("pages-frontend/nemo-guide.js")
    m = re.search(r"function closePanel\(\) \{(.*?)\n  \}", src, re.DOTALL)
    assert m, "closePanel not found"
    assert "CustodianTour.dismissAssistant()" in m.group(1), (
        "closePanel() must set the shared assistant_dismissed flag"
    )


def test_nemo_guide_auto_open_respects_shared_dismissed_flag():
    """The auto-open gate must also check the shared assistant_dismissed
    flag, not just this widget's own per-page dismissed map -- otherwise a
    minimize on operator.html/triage.html/console.html wouldn't stop
    nemo-guide.js from popping open on Home/Tools/Docs.
    """
    src = read_text("pages-frontend/nemo-guide.js")
    m = re.search(r"const isDismissed = (.*?);\n", src, re.DOTALL)
    assert m, "isDismissed definition not found"
    assert "assistant_dismissed" in m.group(1), (
        "isDismissed must also factor in the shared CustodianTour "
        "assistant_dismissed flag"
    )
