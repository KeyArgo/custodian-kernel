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


def test_integrations_page_has_guidance_and_knows_codex_guard_and_talaria():
    """Live incident 2026-07-21: a visitor on /integrations asked Nemotron
    about Codex Guard and Talaria -- the exact topic of the page -- and it
    denied knowing about either, because there was no _PAGE_GUIDANCE entry
    for 'integrations' at all (the page didn't exist when SYSTEM_PROMPT was
    written) and the base prompt only knows about refunds/claims/disposition.
    """
    assert 'integrations' in nemotron_chat._PAGE_GUIDANCE
    guidance = nemotron_chat._PAGE_GUIDANCE['integrations']
    assert 'Codex Guard' in guidance
    assert 'Talaria' in guidance
    assert 'do not deny' in guidance.lower() or "don't deny" in guidance.lower()


def test_integrations_page_also_knows_paladin():
    """Same incident class as above, found 2026-07-23: Codex Guard and Talaria
    got added to _INTEGRATIONS_GUIDANCE and FALLBACK_SYSTEM together, but
    Paladin -- the credential broker underneath both -- was never added to
    either, so a visitor asking Nemotron about Paladin got told it doesn't
    exist, including in the degraded/fallback lane."""
    guidance = nemotron_chat._PAGE_GUIDANCE['integrations']
    assert 'Paladin' in guidance
    assert 'do not deny' in guidance.lower() or "don't deny" in guidance.lower()


def test_paladin_page_has_guidance_and_does_not_deny_itself():
    assert 'paladin' in nemotron_chat._PAGE_GUIDANCE
    guidance = nemotron_chat._PAGE_GUIDANCE['paladin']
    assert 'sandboxed egress' in guidance.lower()
    assert 'do not deny' in guidance.lower() or "don't deny" in guidance.lower()
