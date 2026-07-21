"""Regression 2026-07-21 (live incident): SYSTEM_PROMPT's core self-description
("you read messy customer messages... extract structured claims... that
proposal is all you produce. You cannot act on it.") is the Triage page's
role, but every page shares the same base SYSTEM_PROMPT with per-page
guidance only ever appended, never overriding it. On the Operator page --
where Nemotron is instead framed as the one whose spend/earn REQUEST the
kernel evaluates -- a visitor asking the same question twice got two
contradictory answers: once from the Operator framing, once reverting to
the base "I only read messages, I don't execute spends" self-description.
_OPERATOR_GUIDANCE must explicitly override that framing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.nemotron_chat as nemotron_chat


def test_operator_guidance_overrides_triage_self_description():
    guidance = nemotron_chat._OPERATOR_GUIDANCE
    assert "OVERRIDE" in guidance
    assert "bystander" in guidance.lower()
    assert "triage" in guidance.lower()
