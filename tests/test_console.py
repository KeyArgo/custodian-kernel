"""Tests for the live operator firewall console (custodian.cli.cmd_console)."""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from custodian.cli.cmd_console import (
    _age, _confirm, _draw, _remaining, _snooze, _snoozes, run,
)
from custodian.codex_guard.receipts import ReceiptChain
from custodian.codex_guard.approvals import ApprovalRecord, ApprovalStore
from custodian.control.policy import ApprovalPolicy, ApprovalRule
from custodian.control.filesystem_policy import FilesystemPolicy, FilesystemRule
from custodian.executor.capability import CapabilityRecord, CapabilityStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(state_dir: Path, operator: str = "test-operator"):
    return SimpleNamespace(state_dir=str(state_dir), operator=operator)


def _seed_codex_pending(state_dir: Path, requester: str = "codex-agent",
                        ttl: int = 300) -> ApprovalRecord:
    store = ApprovalStore(state_dir)
    return store.request(digest="ab" * 32, requester=requester, ttl_seconds=ttl)


def _seed_exec_pending(state_dir: Path, requester: str = "exec-agent",
                       ttl: int = 300) -> CapabilityRecord:
    store = CapabilityStore(state_dir)
    cap = store.request(digest="cd" * 32, requester=requester, ttl_seconds=ttl)
    return cap


# ---------------------------------------------------------------------------
# _remaining / _age formatting
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_remaining_zero(self):
        class Fake:
            expires_at = time.time()
        assert _remaining(Fake()) == "00:00"

    def test_remaining_future(self):
        fake_time = 1000.0
        class Fake:
            expires_at = fake_time + 125
            created_at = fake_time
        with patch("custodian.cli.cmd_console.time.time", return_value=fake_time):
            assert _remaining(Fake()) == "02:05"

    def test_remaining_never_negative(self):
        class Fake:
            expires_at = time.time() - 60
        assert _remaining(Fake()) == "00:00"

    def test_age_seconds(self):
        class Fake:
            created_at = time.time() - 45
        assert _age(Fake()) == "45s"

    def test_age_minutes_and_seconds(self):
        class Fake:
            created_at = time.time() - 185
        assert _age(Fake()) == "3m5s"

    def test_age_zero(self):
        class Fake:
            created_at = time.time()
        assert _age(Fake()) == "0s"


# ---------------------------------------------------------------------------
# _confirm
# ---------------------------------------------------------------------------

class TestConfirm:
    def test_yes_returns_true(self):
        with patch("custodian.cli.cmd_console._key", return_value="y"):
            assert _confirm("Proceed?") is True

    def test_no_returns_false(self):
        with patch("custodian.cli.cmd_console._key", return_value="n"):
            assert _confirm("Proceed?") is False

    def test_enter_returns_false(self):
        with patch("custodian.cli.cmd_console._key", return_value=""):
            assert _confirm("Proceed?") is False

    def test_uppercase_Y_returns_true(self):
        with patch("custodian.cli.cmd_console._key", return_value="y"):
            assert _confirm("Proceed?") is True


# ---------------------------------------------------------------------------
# _draw — dashboard rendering
# ---------------------------------------------------------------------------

class TestDraw:
    def test_empty_dashboard_shows_waiting_message(self, tmp_path, capsys):
        approvals, capabilities, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "No actions waiting" in out
        assert "CUSTODIAN CONTROL PLANE" in out
        assert "FAIL-CLOSED" in out
        assert len(pending) == 0

    def test_shows_pending_codex_record(self, tmp_path, capsys):
        rec = _seed_codex_pending(tmp_path)
        approvals, capabilities, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "WAITING" in out
        assert "CODEX" in out
        assert rec.requester in out
        assert "digest=" in out
        assert len(pending) == 1

    def test_shows_pending_exec_record(self, tmp_path, capsys):
        cap = _seed_exec_pending(tmp_path)
        approvals, capabilities, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "WAITING" in out
        assert "EXEC" in out
        assert cap.requester in out
        assert len(pending) == 1

    def test_shows_both_integrations(self, tmp_path, capsys):
        _seed_codex_pending(tmp_path)
        _seed_exec_pending(tmp_path)
        approvals, capabilities, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "CODEX" in out
        assert "EXEC" in out
        assert len(pending) == 2

    def test_shows_policy_and_filesystem_counts(self, tmp_path, capsys):
        policy = ApprovalPolicy(tmp_path / "approval-policy.json")
        policy.add(ApprovalRule(mode="ask", adapter="codex", action_kind="write"))
        filesystem = FilesystemPolicy(tmp_path / "filesystem-policy.json")
        filesystem.add(FilesystemRule(
            harness="codex", model="*", access="read",
            allow_roots=("/home",), enforcement="routed",
        ))
        _seed_codex_pending(tmp_path)
        approvals, capabilities, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "1 active rule" in out
        assert "1 ask" in out
        assert "Filesystem scopes: 1" in out

    def test_keyboard_help_shown(self, tmp_path, capsys):
        _draw(tmp_path, "")
        out = capsys.readouterr().out
        for key in ("[A]", "[D]", "[I]", "[L]", "[F]", "[R]", "[K]", "[Q]"):
            assert key in out, f"missing {key}"
        assert "approve once" in out
        assert "global stop" in out

    def test_ignore_hides_but_does_not_authorize(self, tmp_path, capsys):
        record = _seed_codex_pending(tmp_path)
        _snooze(tmp_path, record.approval_id, seconds=300)
        assert record.approval_id in _snoozes(tmp_path)
        _, _, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert not pending
        assert "Snoozed 1" in out
        assert ApprovalStore(tmp_path).get(record.approval_id).status == "pending"

    def test_approve_once_explanation_shown(self, tmp_path, capsys):
        _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "Approve-once" in out
        assert "single-use" in out

    def test_lease_and_permanent_explanation(self, tmp_path, capsys):
        _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "Lease" in out
        assert "Permanent" in out

    def test_message_displayed(self, tmp_path, capsys):
        _draw(tmp_path, "custom message here")
        out = capsys.readouterr().out
        assert "custom message here" in out

    def test_live_indicator_in_header(self, tmp_path, capsys):
        _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "LIVE" in out

    def test_hard_denial_is_persistently_visible(self, tmp_path, capsys):
        ReceiptChain(tmp_path).append({
            "verdict": "denied", "action_kind": "write", "band": "L4",
            "reason": "skills tree is protected",
        }, tool="apply_patch", session_id="test")
        _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "BLOCKED ACTIONS" in out
        assert "skills tree is protected" in out
        assert "hard denials" in out

    def test_tampered_receipt_chain_raises_visible_alert(self, tmp_path, capsys):
        chain = ReceiptChain(tmp_path)
        chain.append({
            "verdict": "denied", "action_kind": "write", "band": "L4",
            "reason": "blocked",
        }, tool="apply_patch", session_id="test")
        chain.path.write_text(chain.path.read_text().replace("blocked", "changed"))
        _draw(tmp_path, "")
        assert "audit verification failed" in capsys.readouterr().out

    def test_max_twelve_pending_shown(self, tmp_path, capsys):
        for i in range(15):
            store = ApprovalStore(tmp_path)
            store.request(digest=f"{i:02x}" * 32, requester=f"user{i}", ttl_seconds=300)
        approvals, capabilities, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert out.count("WAITING") == 12


# ---------------------------------------------------------------------------
# run() — integration-level checks
# ---------------------------------------------------------------------------

class TestRun:
    def test_quit_returns_zero(self, tmp_path):
        with patch("custodian.cli.cmd_console._key", side_effect=["q"]):
            rc = run(_make_args(tmp_path))
        assert rc == 0

    def test_q_does_not_require_pending(self, tmp_path):
        with patch("custodian.cli.cmd_console._key", side_effect=["q"]):
            rc = run(_make_args(tmp_path))
        assert rc == 0

    def test_r_shows_rule_count(self, tmp_path, capsys):
        policy = ApprovalPolicy(tmp_path / "approval-policy.json")
        policy.add(ApprovalRule(mode="ask", adapter="codex", action_kind="write"))
        with patch("custodian.cli.cmd_console._key", side_effect=["r", "q"]):
            run(_make_args(tmp_path))
        out = capsys.readouterr().out
        assert "active rule" in out

    def test_l_adds_lease(self, tmp_path):
        with patch("custodian.cli.cmd_console._key", side_effect=["l", "q"]):
            run(_make_args(tmp_path))
        policy = ApprovalPolicy(tmp_path / "approval-policy.json")
        assert len(policy.list()) == 1
        rule = policy.list()[0]
        assert rule.mode == "auto"
        assert rule.max_uses == 25

    def test_k_without_confirmation_does_not_add_rule(self, tmp_path):
        with patch("custodian.cli.cmd_console._key", side_effect=["k", "q"]):
            with patch("custodian.cli.cmd_console._confirm", return_value=False):
                run(_make_args(tmp_path))
        policy = ApprovalPolicy(tmp_path / "approval-policy.json")
        assert len(policy.list()) == 0

    def test_k_with_confirmation_adds_deny_rule(self, tmp_path):
        with patch("custodian.cli.cmd_console._key", side_effect=["k", "q"]):
            with patch("custodian.cli.cmd_console._confirm", return_value=True):
                run(_make_args(tmp_path))
        policy = ApprovalPolicy(tmp_path / "approval-policy.json")
        assert len(policy.list()) == 1
        assert policy.list()[0].mode == "deny"

    def test_approve_codex_record_updates_status(self, tmp_path):
        rec = _seed_codex_pending(tmp_path)
        with patch("custodian.cli.cmd_console._key", side_effect=["a", "q"]):
            with patch("custodian.cli.cmd_console._draw") as mock_draw:
                approvals = ApprovalStore(tmp_path)
                caps = CapabilityStore(tmp_path)
                mock_draw.return_value = (approvals, caps, [("CODEX", rec)])
                run(_make_args(tmp_path))
        approved = approvals.get(rec.approval_id)
        assert approved.status == "approved"
        assert approved.approved_by == "test-operator"

    def test_deny_codex_record_updates_status(self, tmp_path):
        rec = _seed_codex_pending(tmp_path)
        with patch("custodian.cli.cmd_console._key", side_effect=["d", "q"]):
            with patch("custodian.cli.cmd_console._draw") as mock_draw:
                approvals = ApprovalStore(tmp_path)
                caps = CapabilityStore(tmp_path)
                mock_draw.return_value = (approvals, caps, [("CODEX", rec)])
                run(_make_args(tmp_path))
        denied = approvals.get(rec.approval_id)
        assert denied.status == "denied"

    def test_approve_exec_record_updates_status(self, tmp_path):
        cap = _seed_exec_pending(tmp_path)
        with patch("custodian.cli.cmd_console._key", side_effect=["a", "q"]):
            with patch("custodian.cli.cmd_console._draw") as mock_draw:
                approvals = ApprovalStore(tmp_path)
                caps = CapabilityStore(tmp_path)
                mock_draw.return_value = (approvals, caps, [("EXEC", cap)])
                run(_make_args(tmp_path))
        approved = caps.get(cap.capability_id)
        assert approved.status == "approved"
        assert approved.approved_by == "test-operator"

    def test_deny_exec_record_updates_status(self, tmp_path):
        cap = _seed_exec_pending(tmp_path)
        with patch("custodian.cli.cmd_console._key", side_effect=["d", "q"]):
            with patch("custodian.cli.cmd_console._draw") as mock_draw:
                approvals = ApprovalStore(tmp_path)
                caps = CapabilityStore(tmp_path)
                mock_draw.return_value = (approvals, caps, [("EXEC", cap)])
                run(_make_args(tmp_path))
        denied = caps.get(cap.capability_id)
        assert denied.status == "denied"


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_draw_error_continues_loop(self, tmp_path):
        call_count = 0

        def flaky_draw(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("draw failure")
            return ApprovalStore(tmp_path), CapabilityStore(tmp_path), []

        with patch("custodian.cli.cmd_console._draw", side_effect=flaky_draw):
            with patch("custodian.cli.cmd_console._key", side_effect=["q"]):
                rc = run(_make_args(tmp_path))
        assert rc == 0
        assert call_count == 2

    def test_key_handler_error_does_not_crash(self, tmp_path):
        def broken_approve(*args, **kwargs):
            raise ApprovalError("broken")
    
        rec = _seed_codex_pending(tmp_path)
        with patch("custodian.cli.cmd_console._key", side_effect=["a", "q"]):
            with patch.object(ApprovalStore, "approve", side_effect=broken_approve):
                with patch("custodian.cli.cmd_console._draw") as mock_draw:
                    approvals = ApprovalStore(tmp_path)
                    caps = CapabilityStore(tmp_path)
                    mock_draw.return_value = (approvals, caps, [("CODEX", rec)])
                    rc = run(_make_args(tmp_path))
        assert rc == 0

    def test_empty_pending_a_and_d_noop(self, tmp_path, capsys):
        with patch("custodian.cli.cmd_console._key", side_effect=["a", "d", "q"]):
            rc = run(_make_args(tmp_path))
        assert rc == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_expired_records_not_shown(self, tmp_path, capsys):
        store = ApprovalStore(tmp_path)
        store.request(digest="ef" * 32, requester="expired", ttl_seconds=1)
        time.sleep(1.1)
        approvals, capabilities, pending = _draw(tmp_path, "")
        out = capsys.readouterr().out
        assert "No actions waiting" in out
        assert len(pending) == 0

    def test_register_adds_console_parser(self, tmp_path):
        import argparse
        sub = argparse.ArgumentParser().add_subparsers()
        from custodian.cli.cmd_console import register
        register(sub, str(tmp_path))
        # Should parse without error
        parsed = argparse.ArgumentParser().add_subparsers()
        register(parsed, str(tmp_path))
        args = parsed.choices["console"].parse_args(["--state-dir", str(tmp_path)])
        assert args.state_dir == str(tmp_path)

    def test_register_default_operator(self, tmp_path):
        import argparse
        sub = argparse.ArgumentParser().add_subparsers()
        from custodian.cli.cmd_console import register
        register(sub, str(tmp_path))
        args = sub.choices["console"].parse_args(["--state-dir", str(tmp_path)])
        assert args.operator is not None
