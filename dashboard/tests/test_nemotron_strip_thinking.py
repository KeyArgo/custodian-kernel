"""Unit tests for the Nemotron response post-processing.

The nemotron_chat module has several pure functions that handle
the model's output: stripping reasoning tokens, stripping constraint
preamble, rewriting markdown links to jumps. These are testable in
isolation without making a real Nemotron call.

Regression test for bug-hunt 2026-07-03: when Nemotron's entire
response is just the constraint preamble (no actual answer), the
stripper used to fall back to returning the original text — leaking
the model's self-talk to the user. Now it returns '' so the frontend
shows a clear "Nemotron returned an empty response" status.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dashboard/, for `import api.*`


def test_strip_thinking_returns_empty_when_response_is_only_constraint_preamble():
    """Bug-hunt 2026-07-03: a single-line response like 'We need to
    respond with first response must include...' was being passed through
    to the user because the stripper's fallback returned text.strip()
    when the cleaned result was empty. The user saw the model talking
    to itself.

    Fix: when the line-by-line scan finds nothing useful, return ''.
    """
    from api.nemotron_chat import _strip_thinking
    constraint_only = (
        "We need to respond with first response must include "
        "[[jump:operator|the operator panel]] as clickable link in body. "
        "Must be under 150 words, one or two short paragraphs, plain "
        "language, friendly, self"
    )
    result = _strip_thinking(constraint_only)
    assert result == '', (
        f"_strip_thinking should return '' when the entire response is "
        f"constraint preamble. Got: {result[:200]!r}"
    )


def test_strip_thinking_keeps_real_prose_after_constraint():
    """Sanity check: the stripper must NOT remove the actual answer
    that follows the constraint preamble.
    """
    from api.nemotron_chat import _strip_thinking
    text = (
        "We need to respond with first response must include [[jump:foo|bar]].\n"
        "This is the real answer with the jump link baked in.\n"
        "It has multiple lines of actual content."
    )
    result = _strip_thinking(text)
    # The preamble is gone, the real answer is preserved
    assert "We need to" not in result, "Preamble should be stripped"
    assert "This is the real answer" in result, "Real answer should be kept"
    assert "multiple lines" in result, "Subsequent lines should be kept"


def test_strip_thinking_strips_actual_think_tags():
    """Sanity check: <think>...</think> blocks are removed first.
    """
    from api.nemotron_chat import _strip_thinking
    text = "<think>the model's reasoning</think>The actual reply."
    result = _strip_thinking(text)
    assert "<think>" not in result
    assert "reasoning" not in result
    assert "The actual reply." in result


def test_strip_thinking_returns_input_unchanged_when_no_preamble():
    """Sanity check: the fast path leaves non-constraint responses alone.
    """
    from api.nemotron_chat import _strip_thinking
    text = "This is a perfectly normal reply with no preamble."
    result = _strip_thinking(text)
    assert result == text


def test_strip_thinking_handles_empty_input():
    """Sanity check: empty input returns empty.
    """
    from api.nemotron_chat import _strip_thinking
    assert _strip_thinking("") == ""
    assert _strip_thinking(None) is None


def test_strip_thinking_handles_multiline_constraint_then_real_answer():
    """Regression: when the preamble spans multiple lines (one
    constraint line, one blank line, one more constraint line, then
    real prose), the stripper must keep the real prose and drop the
    preamble.
    """
    from api.nemotron_chat import _strip_thinking
    text = (
        "We need to respond with first person.\n"
        "\n"
        "Must include [[jump:operator|the operator panel]] in body.\n"
        "\n"
        "The actual answer starts here with multiple lines of real prose.\n"
        "More content on the second line."
    )
    result = _strip_thinking(text)
    assert "We need to" not in result
    assert "Must include" not in result
    assert "The actual answer" in result
    assert "More content" in result
