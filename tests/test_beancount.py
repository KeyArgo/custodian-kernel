"""Tests for custodian beancount export command."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pytest

from custodian.cli import cmd_beancount
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    d = tmp_path / "state"
    d.mkdir()
    return d


def _ns(state_dir: str, since: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(state_dir=state_dir, since=since)


class TestBeancountEmpty:
    """With an empty ledger, the output is a valid Beancount header."""

    def test_no_db_emits_header(self, state_dir, capsys):
        rc = cmd_beancount.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "; Custodian beancount export" in out
        assert "; Generated:" in out
        assert "; No entries." in out

    def test_empty_db_emits_header(self, state_dir, capsys):
        SqliteStorage(state_dir / "custodian.db")
        rc = cmd_beancount.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "; No entries." in out

    def test_header_is_valid_beancount(self, state_dir, capsys):
        """All lines in the empty case must be valid Beancount comments."""
        rc = cmd_beancount.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        for line in out.splitlines():
            # Either blank, a `;` comment, or an `option` directive.
            assert line == "" or line.startswith(";") or line.startswith("option "), line


class TestBeancountWithEntries:
    """Each ledger entry should produce a 3-line Beancount transaction."""

    def test_single_entry_three_lines(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(
                event="executed",
                amount=0.50,
                description="http-get",
                band=Band.L2,
                ts=time.mktime(time.strptime("2026-06-29 14:30:00", "%Y-%m-%d %H:%M:%S")),
            )
        )
        rc = cmd_beancount.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        # The transaction block contains: date * "narration", one posting with
        # an amount, and a second posting (no amount). That's 3 lines.
        assert '2026-06-29 * "custodian-spend: http-get"' in out
        assert "Assets:Agent:Test" in out
        assert "0.50 USD" in out
        assert "Expenses:Agent:http-get" in out

    def test_multiple_entries_render(self, state_dir, capsys):
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=1.0, description="skill-a", band=Band.L2,
                       ts=time.mktime(time.strptime("2026-06-28 10:00:00", "%Y-%m-%d %H:%M:%S")))
        )
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=2.0, description="skill-b", band=Band.L2,
                       ts=time.mktime(time.strptime("2026-06-29 10:00:00", "%Y-%m-%d %H:%M:%S")))
        )
        rc = cmd_beancount.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        assert "skill-a" in out
        assert "skill-b" in out
        # Two transaction headers means at least 6 non-blank non-comment lines
        transaction_lines = [l for l in out.splitlines()
                             if l and not l.startswith(";") and not l.startswith("option ")]
        assert len(transaction_lines) >= 6

    def test_since_filter(self, state_dir, capsys):
        """--since YYYY-MM-DD keeps only entries on/after that date."""
        storage = SqliteStorage(state_dir / "custodian.db")
        # Old entry — should be filtered out
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=1.0, description="old-skill", band=Band.L2,
                       ts=time.mktime(time.strptime("2025-01-01 00:00:00", "%Y-%m-%d %H:%M:%S")))
        )
        # New entry — should be included
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=2.0, description="new-skill", band=Band.L2,
                       ts=time.mktime(time.strptime("2026-06-29 00:00:00", "%Y-%m-%d %H:%M:%S")))
        )
        rc = cmd_beancount.run(_ns(str(state_dir), since="2026-01-01"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "new-skill" in out
        assert "old-skill" not in out

    def test_invalid_since_date_errors(self, state_dir, capsys):
        with pytest.raises(SystemExit) as excinfo:
            cmd_beancount.run(_ns(str(state_dir), since="not-a-date"))
        assert excinfo.value.code == 1
        err = capsys.readouterr().err
        assert "invalid --since date" in err

    def test_special_chars_in_description_sanitized(self, state_dir, capsys):
        """Whitespace/punctuation in the skill name is sanitized for the account."""
        storage = SqliteStorage(state_dir / "custodian.db")
        storage.append_audit_entry(
            AuditEntry(
                event="executed", amount=1.0, description="http get!",
                band=Band.L2,
                ts=time.mktime(time.strptime("2026-06-29 14:30:00", "%Y-%m-%d %H:%M:%S")),
            )
        )
        rc = cmd_beancount.run(_ns(str(state_dir)))
        assert rc == 0
        out = capsys.readouterr().out
        # The posting account should have sanitized the skill, not have raw
        # spaces or exclamation marks.
        assert "Expenses:Agent:http-get!" not in out
        assert "Expenses:Agent:http-get" in out
