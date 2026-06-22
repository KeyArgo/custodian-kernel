"""Tests for the kill switch: storage round-trip and evaluator override.

The kill switch is a real, general-purpose feature of the engine, not
demo-only glue -- any caller (our CLI, our dashboard, a different control
surface entirely) consults the same custodian.storage.get_kill_switch() and
the same custodian.policy.decide(killed=...) parameter. These tests exercise
exactly that path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from custodian.policy.evaluator import decide
from custodian.policy.loader import parse_policy
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuthorityState, Band, KillSwitchState, SpendRequest, Verdict


@pytest.fixture
def storage(tmp_path: Path) -> SqliteStorage:
    return SqliteStorage(tmp_path / "test.db")


@pytest.fixture
def policy_path(tmp_path: Path) -> Path:
    p = tmp_path / "policy.yaml"
    p.write_text(yaml.dump({
        "version": "1.0",
        "default_band": "L2",
        "bands": {
            "L2": {"max_spend": 2.0, "requires_approval": False, "approval_backend": "twilio_verify"},
        },
        "rules": [],
    }))
    return p


class TestKillSwitchStorage:
    def test_default_is_not_killed(self, storage: SqliteStorage):
        state = storage.get_kill_switch()
        assert state.killed is False

    def test_engage_and_persist(self, storage: SqliteStorage):
        storage.set_kill_switch(KillSwitchState(killed=True, reason="testing", by="alice"))
        loaded = storage.get_kill_switch()
        assert loaded.killed is True
        assert loaded.reason == "testing"
        assert loaded.by == "alice"

    def test_release(self, storage: SqliteStorage):
        storage.set_kill_switch(KillSwitchState(killed=True, by="alice"))
        storage.set_kill_switch(KillSwitchState(killed=False, by="alice"))
        assert storage.get_kill_switch().killed is False

    def test_upsert_overwrites_not_duplicates(self, storage: SqliteStorage):
        storage.set_kill_switch(KillSwitchState(killed=True, by="alice"))
        storage.set_kill_switch(KillSwitchState(killed=True, by="bob", reason="second"))
        loaded = storage.get_kill_switch()
        assert loaded.by == "bob"
        assert loaded.reason == "second"


class TestKillSwitchOverridesEverything:
    def test_killed_denies_an_otherwise_autonomous_request(self, policy_path: Path):
        policy = parse_policy(yaml.safe_load(policy_path.read_text()))
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=0.0)
        request = SpendRequest(amount=0.50, description="trivially small")

        not_killed = decide(request, state, policy, killed=False)
        assert not_killed.verdict == Verdict.AUTONOMOUS

        killed = decide(request, state, policy, killed=True)
        assert killed.verdict == Verdict.DENIED
        assert "kill switch" in killed.reason.lower()

    def test_killed_denies_even_a_zero_amount(self, policy_path: Path):
        policy = parse_policy(yaml.safe_load(policy_path.read_text()))
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=0.0)
        request = SpendRequest(amount=0.01, description="negligible")
        decision = decide(request, state, policy, killed=True)
        assert decision.verdict == Verdict.DENIED

    def test_killed_defaults_to_false_for_existing_callers(self, policy_path: Path):
        """Every existing call site that doesn't know about the kill switch
        yet must keep working exactly as before -- killed defaults to False."""
        policy = parse_policy(yaml.safe_load(policy_path.read_text()))
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=0.0)
        request = SpendRequest(amount=1.0, description="no killed arg passed")
        decision = decide(request, state, policy)  # no killed= kwarg at all
        assert decision.verdict == Verdict.AUTONOMOUS
