"""Refund triage pack: invariants that must hold for the platform to be
trustworthy. These are the load-bearing claims of the demo, so they get tests.
"""
import json
from pathlib import Path

import pytest

from custodian.packs.base import Envelope, ClaimStatus
from custodian.packs.engine import triage, replay_with_policy_change
from custodian.packs.refunds.pack import RefundPack, APPROVE, DENY, FLAG_ABUSE, ESCALATE_AMBIGUOUS
from custodian.policy.loader import load_policy
from custodian.types import AuthorityState, Band

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "custodian" / "packs" / "refunds" / "corpus"
KERNEL_POLICY = REPO / "custodian" / "packs" / "refunds" / "policy.yaml"


@pytest.fixture
def pack():
    return RefundPack()


@pytest.fixture
def kernel_policy():
    return load_policy(KERNEL_POLICY)


@pytest.fixture
def state():
    return AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=1000.0)


def _case(name):
    data = json.loads((CORPUS / name).read_text())
    return data, Envelope.from_dict(data["envelope"])


@pytest.mark.parametrize("filename", sorted(p.name for p in CORPUS.glob("*.json")))
def test_corpus_matches_expected_disposition(filename, pack, kernel_policy, state):
    data, env = _case(filename)
    result = triage(pack, env, kernel_policy, state)
    assert result.adapter_disposition == data["expect"], (
        f"{filename}: got {result.adapter_disposition}, expected {data['expect']}"
    )


def test_every_refund_escalates_to_a_human_regardless(pack, kernel_policy, state):
    """The core safety claim: there is NO autonomous refund path. Every case,
    including a clean in-window approve, lands on a band that requires a human."""
    for f in CORPUS.glob("*.json"):
        _, env = _case(f.name)
        result = triage(pack, env, kernel_policy, state)
        assert result.kernel_verdict == "escalation_required", f.name


def test_planted_lie_overrides_a_confident_approve(pack, kernel_policy, state):
    """The moat. The agent recommends approve with high confidence; ground
    truth contradicts the central claim; the deterministic adapter must refuse
    the recommendation and flag it -- a fluent wrong answer never reaches the
    human as truth."""
    data, env = _case("06-planted-lie.json")
    assert env.recommended_disposition == APPROVE  # the agent was confidently wrong
    assert env.confidence >= 0.8
    result = triage(pack, env, kernel_policy, state)
    assert result.contradictions, "verifier failed to catch the contradiction"
    assert result.adapter_disposition == FLAG_ABUSE
    # the override must be explained with the actual ground-truth value, not vibes
    assert any("order.delivered" in r for r in result.adapter_reasons)


def test_kill_switch_denies_even_a_clean_case(pack, kernel_policy, state):
    _, env = _case("01-clean-approve.json")
    result = triage(pack, env, kernel_policy, state, killed=True)
    assert result.kernel_verdict == "denied"


def test_policy_slider_flips_disposition_without_code_change(pack, kernel_policy, state):
    _, env = _case("03-out-of-window-no-reason.json")
    before, after = replay_with_policy_change(
        pack, env, kernel_policy, state, rule_overrides={"window_days": 45}
    )
    assert before.adapter_disposition == DENY
    assert after.adapter_disposition == APPROVE


def test_agent_cannot_self_clear_a_contradiction(pack, kernel_policy, state):
    """Even if the agent claims high confidence AND recommends approve, a
    contradicted claim still wins. The agent does not get to mark its own
    homework."""
    _, env = _case("06-planted-lie.json")
    env.confidence = 0.99
    env.recommended_disposition = APPROVE
    result = triage(pack, env, kernel_policy, state)
    assert result.adapter_disposition == FLAG_ABUSE
