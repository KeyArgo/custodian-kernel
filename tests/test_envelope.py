"""Tests for Feature 1 — daily_envelope opt-in directive."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from custodian.policy.envelope import WINDOW_SECONDS, check_envelope
from custodian.policy.schema import BandConfig
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band


def _make_band(envelope: float | None = None) -> BandConfig:
    return BandConfig(
        name=Band.L2,
        max_spend=2.00,
        requires_approval=False,
        daily_envelope=envelope,
    )


def _record_executed(storage: SqliteStorage, amount: float, ts: float | None = None) -> None:
    """Write a single executed audit row at the given (or now) timestamp."""
    entry = AuditEntry(
        event="executed",
        amount=amount,
        description=f"historical spend of ${amount:.2f}",
        band=Band.L2,
        ts=ts if ts is not None else time.time(),
    )
    storage.append_audit_entry(entry)


class TestEnvelopeBackwardsCompatibility:
    """The whole point of the directive is that absent == no-op."""

    def test_no_envelope_directive_always_allows(self, tmp_path: Path):
        band = _make_band(envelope=None)
        storage = SqliteStorage(tmp_path / "ledger.db")
        # Storage is irrelevant when no envelope is set.
        assert check_envelope(storage, band, 9999.99) is True
        assert check_envelope(None, band, 9999.99) is True

    def test_envelope_unset_ignores_ledger_total(self, tmp_path: Path):
        band = _make_band(envelope=None)
        storage = SqliteStorage(tmp_path / "ledger.db")
        # 1000 historical dollars in the ledger, but band has no envelope
        # — the request must still be allowed.
        for _ in range(10):
            _record_executed(storage, 100.00)
        assert check_envelope(storage, band, 1000.00) is True


class TestEnvelopeGating:
    """When the band declares an envelope, the gate actually fires."""

    def test_within_envelope_allows(self, tmp_path: Path):
        storage = SqliteStorage(tmp_path / "ledger.db")
        band = _make_band(envelope=50.00)
        _record_executed(storage, 5.00)
        _record_executed(storage, 5.00)
        # 10 spent + 5 new = 15 ≤ 50 → allowed
        assert check_envelope(storage, band, 5.00) is True

    def test_exact_envelope_boundary_allows(self, tmp_path: Path):
        storage = SqliteStorage(tmp_path / "ledger.db")
        band = _make_band(envelope=50.00)
        _record_executed(storage, 30.00)
        _record_executed(storage, 10.00)
        # 40 spent + 10 new = 50 ≤ 50 → allowed (boundary inclusive)
        assert check_envelope(storage, band, 10.00) is True

    def test_exceeds_envelope_blocks(self, tmp_path: Path):
        storage = SqliteStorage(tmp_path / "ledger.db")
        band = _make_band(envelope=50.00)
        _record_executed(storage, 5.00)
        _record_executed(storage, 5.00)
        _record_executed(storage, 5.00)
        # 15 spent + 40 new = 55 > 50 → blocked
        assert check_envelope(storage, band, 40.00) is False

    def test_empty_ledger_blocks_only_when_amount_itself_exceeds(self, tmp_path: Path):
        storage = SqliteStorage(tmp_path / "ledger.db")
        band = _make_band(envelope=10.00)
        assert check_envelope(storage, band, 5.00) is True
        assert check_envelope(storage, band, 10.00) is True
        assert check_envelope(storage, band, 10.01) is False


class TestEnvelopeWindowing:
    """Only spend from the last 24h counts — older spend is irrelevant."""

    def test_old_spend_does_not_count(self, tmp_path: Path):
        storage = SqliteStorage(tmp_path / "ledger.db")
        band = _make_band(envelope=50.00)
        now = time.time()
        # 30 dollars spent 25 hours ago — outside the 24h window.
        _record_executed(storage, 30.00, ts=now - (25 * 3600))
        # Pin "now" to the same reference so the math is deterministic.
        assert check_envelope(storage, band, 50.00, now=now) is True

    def test_just_inside_window_counts(self, tmp_path: Path):
        storage = SqliteStorage(tmp_path / "ledger.db")
        band = _make_band(envelope=50.00)
        now = time.time()
        # 23h59m ago is still inside the window.
        _record_executed(storage, 45.00, ts=now - (23 * 3600 + 59 * 60))
        assert check_envelope(storage, band, 1.00, now=now) is True
        assert check_envelope(storage, band, 10.00, now=now) is False

    def test_only_executed_events_count(self, tmp_path: Path):
        """pending / denied / escalated rows must not contribute to spent_24h."""
        storage = SqliteStorage(tmp_path / "ledger.db")
        band = _make_band(envelope=20.00)
        # A 50-dollar pending row should not count toward the envelope.
        storage.append_audit_entry(AuditEntry(
            event="pending_approval", amount=50.00,
            description="never executed", band=Band.L2,
        ))
        # A 50-dollar denied row should not count either.
        storage.append_audit_entry(AuditEntry(
            event="denied", amount=50.00,
            description="explicitly denied", band=Band.L2,
        ))
        # 0 effective prior spend → a 20-dollar request fits exactly.
        assert check_envelope(storage, band, 20.00) is True
        assert check_envelope(storage, band, 20.01) is False

    def test_window_constant_is_24_hours(self):
        assert WINDOW_SECONDS == 86400
