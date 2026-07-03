"""Regression tests for bug-hunt fixes 2026-07-02.

These tests are pure source-code inspections — no live API calls, no model
invocations. They assert the specific code-level fixes for the bugs that
were squashed during the bug-hunt session.

Bugs covered:
- nemotron_chat: max_tokens too low for reasoning model (would truncate)
- nemotron_chat: dead OpenRouter fallback model (would 404)
- nemotron_chat: chat_template_kwargs.thinking sent to OpenRouter (would 422)
- stripe_webhook: demo_earn accepted any amount, no validation, no description cap
- operator.html: nemoNarrate committed user message to history before fetch,
  corrupting context on fetch failure
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def read_text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ── nemotron_chat.py ─────────────────────────────────────────────────────────

def test_openrouter_model_default_is_a_live_model():
    """`OPENROUTER_MODEL` default in nemotron_chat.py must be a model that
    actually returns 200 from openrouter.ai/api/v1/models.

    The previous default `nvidia/llama-3.3-nemotron-super-49b-v1` (no `.5`
    suffix) was 404 on OpenRouter as of 2026-07-02. The free-tier super
    model `nvidia/nemotron-3-super-120b-a12b:free` is the one that works.
    """
    src = read_text("dashboard/api/nemotron_chat.py")
    # Find the OPENROUTER_MODEL definition
    m = re.search(r"OPENROUTER_MODEL\s*=\s*os\.environ\.get\(\s*'OPENROUTER_FALLBACK_MODEL'\s*,\s*'([^']+)'\s*\)", src)
    assert m, "OPENROUTER_MODEL definition not found in expected form"
    default_model = m.group(1)
    assert default_model == "nvidia/nemotron-3-super-120b-a12b:free", (
        f"OPENROUTER_MODEL default should be the working free model, got: {default_model!r}"
    )


def test_openrouter_payload_has_sufficient_max_tokens():
    """`_call_openrouter` must request at least 4000 max_tokens so the
    reasoning model can produce a real answer after its CoT.

    Previous: 600 truncated answers to a single sentence.
    """
    src = read_text("dashboard/api/nemotron_chat.py")
    # Find _call_openrouter function
    m = re.search(r"def _call_openrouter\(.*?payload\s*=\s*\{(.*?)\}", src, re.DOTALL)
    assert m, "_call_openrouter not found"
    payload = m.group(1)
    mt = re.search(r"'max_tokens'\s*:\s*(\d+)", payload)
    assert mt, "max_tokens not in _call_openrouter payload"
    val = int(mt.group(1))
    assert val >= 4000, f"_call_openrouter max_tokens should be >= 4000, got {val}"


def test_openrouter_payload_does_not_send_nim_specific_chat_template_kwargs():
    """`chat_template_kwargs` is a NIM-specific param. OpenRouter returns
    422 for unknown fields. Sending it would 422 the request and the
    fallback path would silently fail.
    """
    src = read_text("dashboard/api/nemotron_chat.py")
    # Find _call_openrouter and look at the payload block (between the { and matching })
    m = re.search(r"def _call_openrouter\(.*?payload\s*=\s*\{(.*?)\n\s+\}", src, re.DOTALL)
    assert m, "_call_openrouter payload block not found"
    payload = m.group(1)
    # Strip comments — the word may appear in a comment explaining why it was removed
    payload_no_comments = "\n".join(
        line for line in payload.split("\n") if not line.strip().startswith("#")
    )
    assert "chat_template_kwargs" not in payload_no_comments, (
        "_call_openrouter must NOT send chat_template_kwargs — that's a NIM param"
    )


def test_nemoclaw_router_call_passes_max_tokens():
    """The /ask route's call to `_nemo_client.complete(...)` must pass an
    explicit max_tokens override of >= 4000. Without this, the default
    of 1200 was used and answers came out truncated.
    """
    src = read_text("dashboard/api/nemotron_chat.py")
    # Find the function body containing the call. Use a non-greedy match that
    # stops at the next `try:` or `except:` after the call.
    m = re.search(
        r"answer\s*=\s*_nemo_client\.complete\((.*?),\s*try:|"
        r"answer\s*=\s*_nemo_client\.complete\((.*?)\n\s+\)\s*\n\s+except",
        src, re.DOTALL
    )
    assert m, "_nemo_client.complete() call not found"
    call_args = m.group(1) or m.group(2)
    mt = re.search(r"max_tokens\s*=\s*(\d+)", call_args)
    assert mt, "_nemo_client.complete() must pass max_tokens explicitly"
    val = int(mt.group(1))
    assert val >= 4000, f"max_tokens for _nemo_client.complete should be >= 4000, got {val}"


# ── stripe_webhook.py ────────────────────────────────────────────────────────

def test_demo_earn_validates_amount():
    """`demo_earn` previously accepted any amount including negatives and
    floats-of-massive-size, polluting /tmp/hermes-earn-ledger.json and
    making the P&L dashboard go negative. Must reject.
    """
    src = read_text("dashboard/api/stripe_webhook.py")
    # Find demo_earn
    m = re.search(r"def demo_earn\(.*?(?=\n\n\ndef |\n@bp\.route|\Z)", src, re.DOTALL)
    assert m, "demo_earn not found"
    body = m.group(0)
    # Must wrap float() in try/except
    assert "except (TypeError, ValueError)" in body, (
        "demo_earn must wrap float() in try/except to reject non-numeric input"
    )
    # Must check amount range
    assert "amount <= 0" in body, "demo_earn must reject amount <= 0"
    assert "amount > " in body, "demo_earn must cap amount at a sane upper bound"
    # Description must be length-capped
    assert "[:200]" in body or ".slice(" in body, "demo_earn must cap description length"


# ── tour-tracker.js ──────────────────────────────────────────────────────────

def test_tour_tracker_triage_runs_count_uses_total_not_array_length():
    """`triage_runs_count` in buildContext() must reflect the user's
    total-in-tab run count, not just the last 20 kept in `s.triage_runs`.

    Previously: `triage_runs_count: runs.length` — but `runs` is already
    sliced to the last 20. After 21 runs, the count would freeze at 20
    forever, breaking Nemotron's "if (runs.length === 0) nudge to /triage"
    logic.
    """
    src = read_text("pages-frontend/tour-tracker.js")
    # The track() function for 'triage_run' must increment a separate counter
    assert "s.triage_runs_total" in src, (
        "tour-tracker.js must track a separate triage_runs_total counter that "
        "increments on every run, not just the array length"
    )
    # buildContext must use the total, not runs.length
    m = re.search(r"triage_runs_count:\s*([^,\n]+)", src)
    assert m, "triage_runs_count not found in buildContext"
    expr = m.group(1).strip()
    # Should reference the total, not bare `runs.length`
    assert expr != "runs.length", (
        "triage_runs_count must not use runs.length (which is capped at 20)"
    )
    assert "triage_runs_total" in expr or "s.triage_runs_total" in expr, (
        f"triage_runs_count should use triage_runs_total, got: {expr!r}"
    )

def test_nemonarrate_does_not_push_user_message_before_fetch():
    """Regression: nemoNarrate() in operator.html used to push the user
    message to opNemoHistory BEFORE the fetch. If the fetch failed (502/503/
    network), the history would have an orphaned user message with no
    assistant reply — corrupting the next narration's context.

    The fix moves both pushes (user message + assistant reply) inside the
    try block, after a successful response. So on failure, history is
    unchanged.
    """
    src = read_text("pages-frontend/operator.html")
    # Find nemoNarrate
    m = re.search(r"async function nemoNarrate\(.*?\n\}\n", src, re.DOTALL)
    assert m, "nemoNarrate not found"
    body = m.group(0)
    # The user message push must be AFTER the fetch (i.e. after the `try` block)
    # Find positions of key markers
    fetch_pos = body.find("await fetch('/api/v1/nemotron/ask'")
    push_pos = body.find("opNemoHistory.push")
    assert fetch_pos > 0, "fetch call not found in nemoNarrate"
    assert push_pos > 0, "history push not found in nemoNarrate"
    assert push_pos > fetch_pos, (
        f"opNemoHistory.push (L{body[:push_pos].count(chr(10))+1}) must be AFTER the "
        f"await fetch (L{body[:fetch_pos].count(chr(10))+1}). Found push at line "
        f"{body[:push_pos].count(chr(10))+1}, fetch at line {body[:fetch_pos].count(chr(10))+1}."
    )
