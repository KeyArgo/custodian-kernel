"""Purchasing (accounts payable) pack: pack #2, proving the engine is reusable.

These tests assert two things the refund pack can't: (1) the SAME engine,
verifier, and kernel run an entirely different business operation with no
engine changes, and (2) this pack actually has an autonomous path -- a small,
clean, approved-vendor invoice pays with no human -- while everything risky
still escalates. The lie-catch invariant is identical and just as load-bearing.
"""
import json
from pathlib import Path

import pytest

from custodian.packs.base import Envelope
from custodian.packs.engine import triage
from custodian.packs.purchasing.pack import PurchasingPack, AUTO_PAY, ESCALATE, FLAG_HOLD
from custodian.policy.loader import load_policy
from custodian.types import AuthorityState, Band

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "custodian" / "packs" / "purchasing" / "corpus"
KERNEL_POLICY = REPO / "custodian" / "packs" / "purchasing" / "policy.yaml"


@pytest.fixture
def pack():
    return PurchasingPack()


@pytest.fixture
def kernel_policy():
    return load_policy(KERNEL_POLICY)


@pytest.fixture
def state():
    # Generous caps -- the kernel band comes from the pack policy, not this state.
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


def test_clean_invoice_pays_autonomously(pack, kernel_policy, state):
    """The path refunds never have: a small, clean, approved-vendor invoice
    that matches its PO actually executes with no human in the loop."""
    _, env = _case("01-clean-autopay.json")
    result = triage(pack, env, kernel_policy, state)
    assert result.adapter_disposition == AUTO_PAY
    assert result.kernel_verdict == "autonomous"
    assert result.final_action == "executed_autonomously"


def test_inflated_invoice_lie_is_caught_and_held(pack, kernel_policy, state):
    """The moat, restated for payables: a vendor over-billing against its
    authorized PO produces a CONTRADICTED claim, and money is held no matter
    how clean the invoice text reads or what the agent recommended."""
    data, env = _case("03-inflated-invoice.json")
    result = triage(pack, env, kernel_policy, state)
    assert result.contradictions, "verifier failed to catch the over-billing"
    assert result.adapter_disposition == FLAG_HOLD
    assert result.final_action != "executed_autonomously"


def test_kernel_allowing_the_amount_cannot_release_a_flagged_payment(pack, kernel_policy, state):
    """final_action is the honest outcome: even when the kernel band would
    permit the amount, a disposition the domain did NOT bless as autonomous
    still goes to a human. Two independent gates; both must say yes."""
    for filename in ("04-unapproved-vendor.json", "05-duplicate-invoice.json"):
        _, env = _case(filename)
        result = triage(pack, env, kernel_policy, state)
        # the kernel, on amount alone, would allow these (small amounts, L1 band)
        assert result.kernel_verdict == "autonomous", filename
        # ...but the domain layer didn't clear autonomy, so money does not move
        assert result.adapter_disposition != AUTO_PAY, filename
        assert result.final_action == "needs_human_review", filename


def test_over_threshold_invoice_needs_a_signature(pack, kernel_policy, state):
    """A legitimate but large invoice from an approved vendor escalates: the
    domain blesses nothing autonomous and the kernel band requires approval."""
    _, env = _case("02-over-threshold.json")
    result = triage(pack, env, kernel_policy, state)
    assert result.adapter_disposition == ESCALATE
    assert result.final_action == "needs_human_review"


def test_kill_switch_blocks_even_a_clean_autopay(pack, kernel_policy, state):
    _, env = _case("01-clean-autopay.json")
    result = triage(pack, env, kernel_policy, state, killed=True)
    assert result.kernel_verdict == "denied"
    assert result.final_action == "blocked_kill_switch"
