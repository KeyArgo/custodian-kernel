"""CLI tests for custodian/cli/ -- exercises the actual main() entry point
with real argv, real SqliteStorage, real policy files on disk. Twilio is
mocked at the _twilio_backend() construction point (not the HTTP layer)
since the whole point of that backend is that the real code never touches
this process -- there is nothing meaningful to integration-test there
without a live Twilio account.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from custodian.cli.main import main
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuthorityState, Band, KillSwitchState, PendingApproval


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


class TestInit:
    def test_creates_workspace_structure(self, tmp_path, capsys):
        target = tmp_path / "workspace"
        rc = main(["init", "--dir", str(target)])
        assert rc == 0
        assert (target / "policy.yaml").exists()
        assert (target / "state").is_dir()
        assert (target / "secrets").is_dir()
        assert (target / "secrets" / "README.md").exists()

    def test_does_not_overwrite_existing_policy(self, tmp_path, capsys):
        target = tmp_path / "workspace"
        target.mkdir()
        (target / "policy.yaml").write_text("# custom policy\n")
        rc = main(["init", "--dir", str(target)])
        assert rc == 0
        assert (target / "policy.yaml").read_text() == "# custom policy\n"
        assert "skipping" in capsys.readouterr().out


class TestValidate:
    def test_valid_policy_prints_bands_and_rules(self, tmp_policy_file, capsys):
        rc = main(["validate", str(tmp_policy_file)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Default band: L2" in out
        assert "L2: max $2.00" in out

    def test_missing_file_errors(self, tmp_path, capsys):
        rc = main(["validate", str(tmp_path / "nope.yaml")])
        assert rc == 1
        assert "no policy file found" in capsys.readouterr().err


class TestStatus:
    def test_no_state_shows_defaults(self, state_dir, capsys):
        rc = main(["status", "--state-dir", str(state_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No authority state initialized" in out
        assert "Band: L2" in out

    def test_with_state_shows_real_values(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.save_authority_state(AuthorityState(
            band=Band.L2, per_action_cap=2.00, session_cap=10.00, spent_this_session=3.40,
        ))
        rc = main(["status", "--state-dir", str(state_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Spent this session: $3.40" in out
        assert "Remaining: $6.60" in out

    def test_kill_switch_engaged_shows_warning(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_kill_switch(KillSwitchState(killed=True, reason="testing", by="Operator"))
        rc = main(["status", "--state-dir", str(state_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "KILL SWITCH ENGAGED" in out
        assert "Operator" in out


class TestRequest:
    def test_in_band_amount_is_autonomous(self, state_dir, tmp_policy_file, capsys):
        rc = main([
            "request", "--amount", "1.00", "--description", "test spend",
            "--state-dir", str(state_dir), "--policy", str(tmp_policy_file),
        ])
        assert rc == 0
        assert "Verdict: AUTONOMOUS" in capsys.readouterr().out

    def test_over_cap_escalates_and_saves_pending(self, state_dir, tmp_policy_file, capsys):
        rc = main([
            "request", "--amount", "45.00", "--description", "big spend",
            "--state-dir", str(state_dir), "--policy", str(tmp_policy_file),
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Verdict: ESCALATION_REQUIRED" in out
        assert "Pending approval saved" in out
        storage = SqliteStorage(state_dir / "custodian.db")
        pending = storage.get_pending_approval()
        assert pending is not None
        assert pending.amount == 45.00

    def test_kill_switch_denies_regardless_of_amount(self, state_dir, tmp_policy_file, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_kill_switch(KillSwitchState(killed=True, reason="demo", by="Operator"))
        rc = main([
            "request", "--amount", "0.50", "--description", "trivial spend",
            "--state-dir", str(state_dir), "--policy", str(tmp_policy_file),
        ])
        assert rc == 3
        assert "DENIED" in capsys.readouterr().out

    def test_negative_amount_rejected(self, state_dir, tmp_policy_file, capsys):
        rc = main([
            "request", "--amount", "-5.00", "--description", "bad",
            "--state-dir", str(state_dir), "--policy", str(tmp_policy_file),
        ])
        assert rc == 1
        assert "must be positive" in capsys.readouterr().err


class TestApprove:
    def test_no_pending_approval_errors(self, state_dir, capsys):
        rc = main(["approve", "123456", "--approved-by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 1
        assert "no pending approval" in capsys.readouterr().err

    def test_expired_pending_errors_and_clears_it(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_pending_approval(PendingApproval(
            amount=5.00, description="old request", reason="test", created_at=0.0,
        ))
        rc = main(["approve", "123456", "--approved-by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 1
        assert "expired" in capsys.readouterr().err
        assert storage.get_pending_approval() is None

    def test_correct_code_approves_and_logs(self, state_dir, monkeypatch, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_pending_approval(PendingApproval(
            amount=45.00, description="real spend", reason="over cap",
        ))

        class FakeBackend:
            def check_response(self, code):
                return code == "654321"

        monkeypatch.setattr("custodian.cli.cmd_approve._twilio_backend", lambda state_dir: FakeBackend())

        rc = main(["approve", "654321", "--approved-by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Approved: $45.00" in out
        assert storage.get_pending_approval() is None
        entries = storage.read_audit_entries()
        assert entries[-1].event == "approved"
        assert entries[-1].approved_by == "Operator"

    def test_wrong_code_rejected(self, state_dir, monkeypatch, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_pending_approval(PendingApproval(amount=45.00, description="real spend", reason="over cap"))

        class FakeBackend:
            def check_response(self, code):
                return False

        monkeypatch.setattr("custodian.cli.cmd_approve._twilio_backend", lambda state_dir: FakeBackend())

        rc = main(["approve", "000000", "--approved-by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 1
        assert "rejected" in capsys.readouterr().err
        # Rejecting a bad code must NOT consume the pending approval -- a
        # mistyped code shouldn't burn the one real request that's waiting.
        assert storage.get_pending_approval() is not None


class TestDeny:
    def test_no_pending_approval_errors(self, state_dir, capsys):
        rc = main(["deny", "--denied-by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 1
        assert "no pending approval" in capsys.readouterr().err

    def test_denies_and_logs(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_pending_approval(PendingApproval(amount=45.00, description="suspicious spend", reason="over cap"))
        rc = main(["deny", "--denied-by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 0
        assert "Denied: $45.00" in capsys.readouterr().out
        assert storage.get_pending_approval() is None
        entries = storage.read_audit_entries()
        assert entries[-1].event == "denied"
        assert entries[-1].denied_by == "Operator"


class TestKillAndResume:
    def test_kill_engages_and_logs(self, state_dir, capsys):
        rc = main(["kill", "--by", "Operator", "--reason", "testing", "--state-dir", str(state_dir)])
        assert rc == 0
        assert "KILL SWITCH ENGAGED" in capsys.readouterr().out
        storage = SqliteStorage(state_dir / "custodian.db")
        assert storage.get_kill_switch().killed is True

    def test_resume_when_not_engaged_is_a_noop(self, state_dir, capsys):
        rc = main(["resume", "--by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 0
        assert "not engaged" in capsys.readouterr().out

    def test_resume_releases_and_logs(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_kill_switch(KillSwitchState(killed=True, reason="r", by="Operator"))
        rc = main(["resume", "--by", "Operator", "--state-dir", str(state_dir)])
        assert rc == 0
        assert "released" in capsys.readouterr().out
        assert storage.get_kill_switch().killed is False

    def test_request_denied_while_engaged_then_succeeds_after_resume(self, state_dir, tmp_policy_file, capsys):
        main(["kill", "--by", "Operator", "--state-dir", str(state_dir)])
        capsys.readouterr()
        rc = main([
            "request", "--amount", "1.00", "--description", "should be denied",
            "--state-dir", str(state_dir), "--policy", str(tmp_policy_file),
        ])
        assert rc == 3
        capsys.readouterr()

        main(["resume", "--by", "Operator", "--state-dir", str(state_dir)])
        capsys.readouterr()
        rc = main([
            "request", "--amount", "1.00", "--description", "should work now",
            "--state-dir", str(state_dir), "--policy", str(tmp_policy_file),
        ])
        assert rc == 0
        assert "AUTONOMOUS" in capsys.readouterr().out


class TestAudit:
    def test_no_database_shows_message(self, state_dir, capsys):
        rc = main(["audit", "--state-dir", str(state_dir)])
        assert rc == 0
        assert "No audit entries found" in capsys.readouterr().out

    def test_filters_by_event_and_respects_limit(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.set_pending_approval(PendingApproval(amount=1.0, description="a", reason="r"))
        main(["deny", "--denied-by", "Operator", "--state-dir", str(state_dir)])
        storage.set_pending_approval(PendingApproval(amount=2.0, description="b", reason="r"))
        main(["deny", "--denied-by", "Operator", "--state-dir", str(state_dir)])
        capsys.readouterr()

        rc = main(["audit", "--state-dir", str(state_dir), "--event", "denied", "--limit", "1"])
        assert rc == 0
        out = capsys.readouterr().out
        assert out.count("denied:") == 1
        assert "$2.00" in out  # the most recent of the two, since audit shows the tail
