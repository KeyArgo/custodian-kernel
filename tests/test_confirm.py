"""Tests for custodian confirm command."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pytest

from custodian.cli import cmd_confirm
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


def _ns(request_id: str, state_dir: str | None = None, deadline: int = 60) -> argparse.Namespace:
    return argparse.Namespace(
        request_id=request_id,
        state_dir=state_dir,
        deadline=deadline,
    )


class TestConfirmLookup:
    """Lookup behavior: not found vs found by payment_intent_id vs by row id."""

    def test_missing_request_returns_error(self, state_dir, capsys):
        SqliteStorage(state_dir / "custodian.db")
        rc = cmd_confirm.run(_ns("pi_doesnotexist", str(state_dir)))
        assert rc == 1
        out = capsys.readouterr().out
        assert "pi_doesnotexist" in out
        assert "not found" in out

    def test_no_db_treated_as_not_found(self, state_dir, capsys):
        rc = cmd_confirm.run(_ns("pi_anything", str(state_dir)))
        assert rc == 1
        assert "not found" in capsys.readouterr().out

    def test_found_by_payment_intent_id(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(
                event="executed",
                amount=1.5,
                description="x",
                band=Band.L2,
                payment_intent_id="pi_test_001",
                ts=time.time(),  # fresh
            )
        )
        rc = cmd_confirm.run(_ns("pi_test_001", str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "✓" in out
        assert "pi_test_001" in out
        assert "within 60s" in out

    def test_found_by_row_id(self, state_dir, capsys):
        """The numeric row id is also accepted as a request id."""
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(
                event="executed",
                amount=2.5,
                description="x",
                band=Band.L2,
                ts=time.time(),
            )
        )
        rc = cmd_confirm.run(_ns("1", str(state_dir)))
        assert rc == 0
        assert "✓" in capsys.readouterr().out


class TestConfirmDeadline:
    """Deadline behavior: within deadline = verified, past = unverified."""

    def test_within_deadline_records_verified(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(
                event="executed",
                amount=1.0,
                description="x",
                band=Band.L2,
                payment_intent_id="pi_fresh",
                ts=time.time(),  # right now → within deadline
            )
        )
        rc = cmd_confirm.run(_ns("pi_fresh", str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "✓" in out
        # A new "verified" entry should be appended
        entries = storage.read_audit_entries()
        assert any(e.event == "verified" for e in entries)
        # Original is unchanged
        original = next(e for e in entries if e.payment_intent_id == "pi_fresh" and e.event == "executed")
        assert original.event == "executed"

    def test_past_deadline_marks_unverified(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        # 120s ago — past the default 60s deadline
        storage.append_audit_entry(
            AuditEntry(
                event="executed",
                amount=1.0,
                description="x",
                band=Band.L2,
                payment_intent_id="pi_old",
                ts=time.time() - 120,
            )
        )
        rc = cmd_confirm.run(_ns("pi_old", str(state_dir)))
        assert rc == 1
        out = capsys.readouterr().out
        assert "✗" in out
        assert "pi_old" in out
        assert "UNVERIFIED" in out
        # A "unverified" entry was appended
        entries = storage.read_audit_entries()
        assert any(e.event == "unverified" for e in entries)
        # The original is still there
        assert any(e.event == "executed" and e.payment_intent_id == "pi_old" for e in entries)

    def test_custom_deadline(self, state_dir, capsys):
        """--deadline overrides the default 60s window."""
        storage = SqliteStorage(state_dir / "custodian.db")
        # 90s ago, but with deadline=120 this is still within window
        storage.append_audit_entry(
            AuditEntry(
                event="executed",
                amount=1.0,
                description="x",
                band=Band.L2,
                payment_intent_id="pi_mid",
                ts=time.time() - 90,
            )
        )
        rc = cmd_confirm.run(_ns("pi_mid", str(state_dir), deadline=120))
        assert rc == 0
        out = capsys.readouterr().out
        assert "✓" in out
        assert "within 120s" in out
