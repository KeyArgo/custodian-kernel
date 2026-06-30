"""Tests for custodian status-banner command."""
from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from custodian.cli import cmd_status_enhanced
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band, KillSwitchState


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


def _ns(state_dir: str) -> argparse.Namespace:
    """Build a minimal argparse Namespace with the only arg run() needs."""
    return argparse.Namespace(state_dir=state_dir)


class TestStatusBannerEmpty:
    """When the ledger is completely empty, the banner shows the fallback message."""

    def test_empty_state_dir_prints_hint(self, state_dir, capsys):
        """No database at all → fallback banner with hint."""
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "ledger empty" in out
        assert "demo verify" in out

    def test_empty_database_prints_hint(self, state_dir, capsys):
        """Database exists but has zero rows → fallback banner."""
        SqliteStorage(state_dir / "custodian.db")
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "ledger empty" in out
        assert "demo verify" in out


class TestStatusBannerWithEntries:
    """When the ledger has spend requests, the banner renders a summary."""

    def test_displays_total_and_verdicts(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=5.0, description="API call", band=Band.L2)
        )
        storage.append_audit_entry(
            AuditEntry(event="denied", amount=30.0, description="Big spend denied", band=Band.L3)
        )
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Total spend requests: 2" in out
        assert "VERIFIED=1" in out
        assert "CONTRADICTED=1" in out
        assert "ESCALATED=0" in out

    def test_last_five_entries_shown(self, state_dir, capsys):
        """Entries 111-115 (latest 5) appear; 101-110 (earliest 5) do not."""
        storage = SqliteStorage(state_dir / "custodian.db")
        for i in range(10):
            storage.append_audit_entry(
                AuditEntry(
                    event="executed",
                    amount=float(101 + i),   # 101..110
                    description=f"early-{i}",
                    band=Band.L2,
                    ts=1000000.0 + i,
                )
            )
        for i in range(10):
            storage.append_audit_entry(
                AuditEntry(
                    event="executed",
                    amount=float(111 + i),   # 111..120
                    description=f"late-{i}",
                    band=Band.L2,
                    ts=2000000.0 + i,
                )
            )
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Last 5 audit entries:" in out
        # Latest 5 (111..120) are shown
        assert "$116.00" in out  # late-5 (116.0)
        assert "$120.00" in out  # late-9 (120.0)
        # Earlier 5 (101..110) are NOT shown
        assert "$101.00" not in out
        assert "$105.00" not in out

    def test_kill_switch_engaged_shows_engaged(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=1.0, description="x", band=Band.L2)
        )
        storage.set_kill_switch(
            KillSwitchState(killed=True, reason="test", by="operator", changed_at=time.time())
        )
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Kill switch: ENGAGED" in out

    def test_kill_switch_default_is_released(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=1.0, description="x", band=Band.L2)
        )
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Kill switch: RELEASED" in out

    def test_today_date_shown_in_header(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=1.0, description="x", band=Band.L2)
        )
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today in out

    def test_unverified_fallback_verdict(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(event="killed", amount=0.0, description="kill switch", band=Band.L0)
        )
        rc = cmd_status_enhanced.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "UNVERIFIED=1" in out
