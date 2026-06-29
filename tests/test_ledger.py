"""Tests for custodian.ledger.Ledger."""
from __future__ import annotations

from pathlib import Path

import pytest

from custodian.ledger import Ledger
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, AuthorityState, Band


@pytest.fixture
def storage(tmp_path: Path) -> SqliteStorage:
    return SqliteStorage(tmp_path / "test.db")


@pytest.fixture
def ledger(storage: SqliteStorage) -> Ledger:
    return Ledger(storage)


class TestRecordSpend:
    def test_record_spend_stores_entry(self, ledger: Ledger, storage: SqliteStorage):
        entry = AuditEntry(
            event="executed",
            amount=45.0,
            description="Backup automation license renewal for NAS systems",
            band=Band.L2,
            approved_by="Operator",
        )
        ledger.record_spend(entry)
        entries = storage.read_audit_entries()
        assert len(entries) == 1
        assert entries[0].amount == 45.0

    def test_record_multiple_spends(self, ledger: Ledger, storage: SqliteStorage):
        for i in range(3):
            entry = AuditEntry(event="executed", amount=float(i + 1) * 10.0, description=f"spend {i}", band=Band.L2)
            ledger.record_spend(entry)
        assert len(storage.read_audit_entries()) == 3


class TestTotalSpent:
    def test_total_spent_all(self, ledger: Ledger):
        ledger.record_spend(
            AuditEntry(event="executed", amount=45.0, description="approved spend", band=Band.L2, approved_by="Operator")
        )
        ledger.record_spend(
            AuditEntry(event="executed", amount=1.50, description="autonomous spend", band=Band.L2)
        )
        assert ledger.total_spent() == 46.50

    def test_total_spent_approved_only(self, ledger: Ledger):
        ledger.record_spend(
            AuditEntry(event="executed", amount=45.0, description="Backup automation license renewal for NAS systems", band=Band.L2, approved_by="Operator")
        )
        ledger.record_spend(
            AuditEntry(event="executed", amount=1.50, description="small autonomous spend", band=Band.L2)
        )
        assert ledger.total_spent(approved_only=True) == 45.0

    def test_total_spent_autonomous_only(self, ledger: Ledger):
        ledger.record_spend(
            AuditEntry(event="executed", amount=45.0, description="big approved", band=Band.L2, approved_by="Operator")
        )
        ledger.record_spend(
            AuditEntry(event="executed", amount=1.50, description="small auto", band=Band.L2)
        )
        assert ledger.total_spent(autonomous_only=True) == 1.50

    def test_total_spent_empty(self, ledger: Ledger):
        assert ledger.total_spent() == 0.0

    def test_total_spent_ignores_non_executed(self, ledger: Ledger):
        ledger.record_spend(AuditEntry(event="escalated", amount=100.0, description="not executed", band=Band.L2))
        assert ledger.total_spent() == 0.0

    def test_total_spent_demonstration_scenario(self, ledger: Ledger):
        ledger.record_spend(
            AuditEntry(event="executed", amount=45.0, description="Backup automation license renewal for NAS systems", band=Band.L2, approved_by="Operator", payment_intent_id="pi_3TkZWEPfSF4TGXT90AWlrnle")
        )
        ledger.record_spend(
            AuditEntry(event="executed", amount=1.50, description="small autonomous spend", band=Band.L2)
        )
        assert ledger.total_spent(approved_only=True) == 45.0
        assert ledger.total_spent(autonomous_only=True) == 1.50
        assert ledger.total_spent() == 46.50


class TestRemainingBudget:
    def test_remaining_budget_full(self, ledger: Ledger):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=0.0)
        assert ledger.remaining_budget(state) == 10.0

    def test_remaining_budget_partial(self, ledger: Ledger):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=4.50)
        assert ledger.remaining_budget(state) == 5.50

    def test_remaining_budget_exhausted(self, ledger: Ledger):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=10.0)
        assert ledger.remaining_budget(state) == 0.0
