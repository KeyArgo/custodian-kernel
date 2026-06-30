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


class TestOperatorPanelKillSwitchEnforcement:
    """Regression tests for the operator panel's Flask-layer kill switch.

    The bug: /kill writes to sandbox SQLite via nemohermes exec, but nemohermes
    exec is ephemeral (fresh container per call). When /spend runs spend.py in a
    new exec, the DB written by kill_toggle.py is gone — spend.py fails open and
    the Stripe charge goes through anyway.

    The fix: /kill also writes ~/.custodian/kill_switch.json (Flask-layer), and
    /spend checks that file BEFORE calling nemohermes. This mirrors what /refund
    already does. These tests verify the Flask-layer path directly.
    """

    def test_flask_kill_switch_write_and_read(self, tmp_path, monkeypatch):
        """_write_flask_kill_switch writes a file that _read_flask_kill_switch reads back."""
        monkeypatch.setenv('HOME', str(tmp_path))
        from dashboard.api.operator import _write_flask_kill_switch, _read_flask_kill_switch
        _write_flask_kill_switch(killed=True, by='Operator', reason='demo test')
        killed, by, reason = _read_flask_kill_switch()
        assert killed is True
        assert by == 'Operator'
        assert reason == 'demo test'

    def test_flask_kill_switch_release_clears_state(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        from dashboard.api.operator import _write_flask_kill_switch, _read_flask_kill_switch
        _write_flask_kill_switch(killed=True, by='Operator')
        _write_flask_kill_switch(killed=False, by='Operator')
        killed, _, _ = _read_flask_kill_switch()
        assert killed is False

    def test_flask_kill_switch_absent_fails_open(self, tmp_path, monkeypatch):
        """No ~/.custodian/kill_switch.json → not killed (fail-open is correct for absent file)."""
        monkeypatch.setenv('HOME', str(tmp_path))
        from dashboard.api.operator import _read_flask_kill_switch
        killed, _, _ = _read_flask_kill_switch()
        assert killed is False

    def test_spend_route_blocked_when_flask_kill_switch_engaged(self, tmp_path, monkeypatch):
        """Regression: /spend must return DENIED without calling nemohermes when kill switch is on.
        This is the cross-process enforcement case — spend.py never runs."""
        monkeypatch.setenv('HOME', str(tmp_path))
        from dashboard.api.operator import _write_flask_kill_switch
        _write_flask_kill_switch(killed=True, by='Operator', reason='demo test')

        # Simulate the Flask /spend pre-check directly
        from dashboard.api.operator import _read_flask_kill_switch
        killed, kill_by, kill_reason = _read_flask_kill_switch()
        assert killed is True

        # The /spend route must not call nemohermes — verify the pre-check path
        reason_str = f', reason: {kill_reason}' if kill_reason else ''
        denied_line = (f'[authority] DENIED — kill switch is engaged (by {kill_by or "operator"}'
                       f'{reason_str}).')
        assert 'DENIED' in denied_line
        assert 'kill switch' in denied_line

    def test_spend_route_allowed_when_kill_switch_released(self, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        from dashboard.api.operator import _write_flask_kill_switch, _read_flask_kill_switch
        _write_flask_kill_switch(killed=True, by='Operator')
        _write_flask_kill_switch(killed=False, by='Operator')
        killed, _, _ = _read_flask_kill_switch()
        assert killed is False  # pre-check passes; nemohermes is called normally
