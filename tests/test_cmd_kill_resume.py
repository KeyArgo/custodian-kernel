"""Tests for custodian kill/resume -- previously untested entirely.

Both commands' own kill-switch state changes were invisible to the
tamper-evident universal ledger (only the legacy JSONL-backed audit_log
saw them) -- the highest-consequence events this kernel has (everything
stops, or starts again) had no hash-chained record. Found in review.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from custodian.cli import cmd_kill, cmd_resume
from custodian.storage.sqlite import SqliteStorage
from custodian.universal_ledger import UniversalLedger


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


def _ns(state_dir: Path, by: str = "operator", reason: str = "") -> argparse.Namespace:
    return argparse.Namespace(state_dir=str(state_dir), by=by, reason=reason)


class TestKill:
    def test_engages_the_kill_switch(self, state_dir, capsys):
        cmd_kill.run(_ns(state_dir, by="alice", reason="incident"))
        storage = SqliteStorage(state_dir / "custodian.db")
        assert storage.get_kill_switch().killed is True
        out = capsys.readouterr().out
        assert "KILL SWITCH ENGAGED by alice" in out

    def test_writes_a_ledger_event(self, state_dir):
        cmd_kill.run(_ns(state_dir, by="alice", reason="incident"))
        ledger = UniversalLedger(state_dir / "ledger.db")
        events = ledger.by_provider("custodian")
        assert len(events) == 1
        assert events[0]["lifecycle_event"] == "denied"
        assert events[0]["action"] == "kill-switch"
        assert "alice" in events[0]["requester"]
        ledger.verify()


class TestResume:
    def test_noop_when_not_engaged(self, state_dir, capsys):
        cmd_resume.run(_ns(state_dir, by="alice"))
        out = capsys.readouterr().out
        assert "not engaged" in out
        ledger = UniversalLedger(state_dir / "ledger.db")
        assert ledger.by_provider("custodian") == []

    def test_releases_the_kill_switch_and_writes_a_ledger_event(self, state_dir):
        cmd_kill.run(_ns(state_dir, by="alice", reason="incident"))
        cmd_resume.run(_ns(state_dir, by="bob"))

        storage = SqliteStorage(state_dir / "custodian.db")
        assert storage.get_kill_switch().killed is False

        ledger = UniversalLedger(state_dir / "ledger.db")
        events = ledger.by_provider("custodian")  # newest first
        assert [e["lifecycle_event"] for e in reversed(events)] == ["denied", "approved"]
        assert events[0]["approver"] == "bob"
        ledger.verify()
