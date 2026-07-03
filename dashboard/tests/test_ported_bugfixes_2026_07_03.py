"""Regression tests for fixes ported from hermes-hackathon-2026 (2026-07-03).

hermes-hackathon-2026 and custodian-dev are two independently-evolving
copies of the same underlying app; fixes made in one have to be manually
re-applied to the other. These tests cover the fixes ported in this pass,
verified against custodian-dev's actual (differently-structured) files
rather than assumed identical to the source repo.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dashboard/, for `import api.*`


def read_text(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ── dashboard/api/nemotron_chat.py ──────────────────────────────────────────

def test_openrouter_model_default_is_a_live_model():
    """The previous default `nvidia/llama-3.3-nemotron-super-49b-v1` (no `.5`
    suffix) 404s on OpenRouter. The free-tier super model is the one that
    actually returns 200.
    """
    from api.nemotron_chat import OPENROUTER_MODEL
    assert OPENROUTER_MODEL == "nvidia/nemotron-3-super-120b-a12b:free"


def test_strip_thinking_drops_pure_constraint_preamble():
    """When Nemotron's entire response is constraint-echo self-talk with no
    real answer, _strip_thinking must return '' rather than leaking it.
    """
    from api.nemotron_chat import _strip_thinking
    garbage = (
        "We need to respond with first response must include the operator "
        "panel as clickable link. Must not mention per_action_cap etc. "
        "Must not mention autonomous_spent etc. Must not mention "
        "autonomous_remaining."
    )
    assert _strip_thinking(garbage) == ""


def test_strip_thinking_keeps_real_prose():
    from api.nemotron_chat import _strip_thinking
    real = "I'm the intelligence layer here — I can request a spend but never approve it myself."
    assert _strip_thinking(real) == real


def test_strip_thinking_strips_think_tags():
    from api.nemotron_chat import _strip_thinking
    text = "<think>internal reasoning here</think>The actual answer for the visitor."
    assert _strip_thinking(text) == "The actual answer for the visitor."


def test_call_openrouter_max_tokens_is_sufficient():
    """Previous 600 truncated reasoning-model answers to a single sentence."""
    src = read_text("dashboard/api/nemotron_chat.py")
    m = re.search(r"def _call_openrouter\(.*?payload\s*=\s*\{(.*?)\n\s+\}", src, re.DOTALL)
    assert m, "_call_openrouter payload block not found"
    mt = re.search(r"'max_tokens'\s*:\s*(\d+)", m.group(1))
    assert mt and int(mt.group(1)) >= 4000


def test_nemoclaw_router_call_passes_max_tokens_and_strips_result():
    """The primary path's answer must be run through this module's own
    _strip_thinking (NemoClawRouter's internal stripper only removes <think>
    tags, not the meta-instruction preamble pattern) and an empty result
    must fall through to the OpenRouter/NIM fallback chain.
    """
    src = read_text("dashboard/api/nemotron_chat.py")
    m = re.search(
        r"answer\s*=\s*_nemo_client\.complete\((.*?)\n\s+\)\s*\n(.*?)except RuntimeError:",
        src, re.DOTALL,
    )
    assert m, "_nemo_client.complete() call not found"
    call_args, post_call = m.group(1), m.group(2)
    mt = re.search(r"max_tokens\s*=\s*(\d+)", call_args)
    assert mt and int(mt.group(1)) >= 4000
    assert "answer = _strip_thinking(answer)" in post_call
    assert re.search(r"if not answer:\s*\n\s+answer\s*=\s*None", post_call)


# ── custodian/inference/router.py ───────────────────────────────────────────

def test_nemoclaw_router_handles_choiceless_200_response():
    """A 200 response under concurrent load can still be a provider error
    body (no "choices" key) -- must be treated as a failure and move to the
    next endpoint instead of raising an uncaught KeyError.
    """
    from custodian.inference.router import NemoClawRouter
    router = NemoClawRouter(endpoints=[])
    src = read_text("custodian/inference/router.py")
    assert 'result.get("choices")' in src
    assert "KeyError" in src and "IndexError" in src


# ── pages-frontend/operator.html ────────────────────────────────────────────

def test_operator_html_esc_is_top_level_scope():
    """Regression: `esc` was defined inside the DOMContentLoaded closure, but
    refreshOpFeed()/refreshLive() are called at script-eval time (before
    DOMContentLoaded fires), which threw "esc is not defined" and left the
    live audit feed empty -- the exact bug reported live.
    """
    src = read_text("pages-frontend/operator.html")
    def_pos = src.find("const esc = s =>")
    dcl_pos = src.find("document.addEventListener('DOMContentLoaded'")
    assert def_pos != -1, "esc definition not found"
    assert dcl_pos != -1, "DOMContentLoaded listener not found"
    assert def_pos < dcl_pos, "esc must be defined before the DOMContentLoaded listener, not inside it"
    # Must not be defined a second time (the old in-closure copy)
    assert src.count("const esc = s =>") == 1


def test_op_nemo_open_does_not_show_placeholder_as_fallback_for_errors():
    """opNemoOpen() used to show 'I'm Nemotron — ask me about any of the demo
    steps.' for both a real empty answer AND an outright backend error,
    making the panel look broken instead of showing a real error.
    """
    src = read_text("pages-frontend/operator.html")
    m = re.search(r"function opNemoOpen\(\).*?opNemoInput\.focus\(\);\s*\}", src, re.DOTALL)
    assert m, "opNemoOpen not found"
    body = m.group(0)
    assert "d.error" in body, "opNemoOpen must have an explicit error branch"
    assert "⚠" in body, "opNemoOpen must show a clearly-marked status for failures"
