"""The opt-in money gates (daily_envelope, margins, no_self_dealing) must fail
CLOSED: if the check itself raises, the request escalates to a human rather
than falling through to the normal band/cap logic and running autonomously.

Regression: each gate was wrapped in `except Exception: log.warning(...);
continue`, so any error inside a check — a storage failure, a malformed
policy, a bug — silently removed the gate. A money gate that disappears on
error is worse than no gate, because the operator believes it is protecting
them. Only the autorank downgrade stays fail-safe-by-continuing, because
skipping it keeps the stricter original band and can never widen authority.
"""
import pytest

from custodian.policy import evaluator
from custodian.policy.schema import (
    BandConfig, MarginsConfig, PoliciesConfig, Policy,
)
from custodian.types import AuthorityState, Band, SpendRequest, Verdict


def _boom(*a, **k):
    raise RuntimeError("check exploded")


def _state():
    return AuthorityState(band=Band.L2, per_action_cap=1000.0,
                          session_cap=1000.0, spent_this_session=0.0)


def _band(**kw):
    return BandConfig(name=Band.L2, max_spend=1000.0, requires_approval=False, **kw)


def test_envelope_gate_fails_closed(monkeypatch):
    monkeypatch.setattr("custodian.policy.envelope.check_envelope", _boom)
    pol = Policy(version="1.0", default_band=Band.L2,
                 bands={Band.L2: _band(daily_envelope=100.0)})
    d = evaluator.decide(SpendRequest(amount=5.0, description="x"), _state(), pol,
                         skill="x", ledger_storage=object())
    assert d.verdict == Verdict.ESCALATION_REQUIRED
    assert "envelope" in d.reason


def test_margin_gate_fails_closed(monkeypatch):
    monkeypatch.setattr("custodian.policy.margin.check_margin", _boom)
    pol = Policy(version="1.0", default_band=Band.L2, bands={Band.L2: _band()},
                 margins=MarginsConfig(minimum_margin=1.0))
    req = SpendRequest(amount=5.0, description="x")
    req.revenue, req.cost = 10.0, 3.0
    d = evaluator.decide(req, _state(), pol, skill="x")
    assert d.verdict == Verdict.ESCALATION_REQUIRED
    assert "margin" in d.reason


def test_self_dealing_gate_fails_closed(monkeypatch):
    monkeypatch.setattr("custodian.policy.self_dealing.check_self_dealing", _boom)
    pol = Policy(version="1.0", default_band=Band.L2, bands={Band.L2: _band()},
                 policies=PoliciesConfig(no_self_dealing=True))
    req = SpendRequest(amount=5.0, description="x")
    req.requester_agent_id, req.recipient_agent_id = "a", "b"
    d = evaluator.decide(req, _state(), pol, skill="x")
    assert d.verdict == Verdict.ESCALATION_REQUIRED
    assert "self_dealing" in d.reason


def test_autorank_failure_keeps_original_band_and_continues(monkeypatch):
    """The one gate that may continue on error: it only downgrades, so skipping
    it keeps the stricter band. A tiny spend must still be autonomous."""
    monkeypatch.setattr("custodian.policy.autorank.apply_autorank", _boom)
    pol = Policy(version="1.0", default_band=Band.L2,
                 bands={Band.L2: _band(band_after_task=Band.L1)})
    d = evaluator.decide(SpendRequest(amount=1.0, description="x"), _state(), pol,
                         skill="x")
    assert d.verdict == Verdict.AUTONOMOUS
