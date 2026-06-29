"""Tests for custodian.audit.AuditLog."""
from __future__ import annotations

from pathlib import Path

import pytest

from custodian.audit import AuditLog
from custodian.exceptions import AuditWriteError
from custodian.types import AuditEntry, Band


@pytest.fixture
def audit_log(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit_log.jsonl")


class TestAppendAndRead:
    def test_append_and_read_back(self, audit_log: AuditLog):
        entry = AuditEntry(
            event="executed",
            amount=45.0,
            description="Backup automation license renewal",
            band=Band.L2,
            approved_by="Operator",
            payment_intent_id="pi_3TkZWEPfSF4TGXT90AWlrnle",
        )
        audit_log.append(entry)
        entries = list(audit_log.read_all())
        assert len(entries) == 1
        assert entries[0].amount == 45.0
        assert entries[0].approved_by == "Operator"

    def test_round_trip_preserves_fields(self, audit_log: AuditLog):
        original = AuditEntry(
            event="executed",
            amount=1.50,
            description="small purchase",
            band=Band.L1,
            approved_by=None,
        )
        audit_log.append(original)
        [restored] = list(audit_log.read_all())
        assert restored.event == original.event
        assert restored.amount == original.amount
        assert restored.description == original.description
        assert restored.band == original.band
        assert restored.approved_by is None

    def test_multiple_entries_read_back_in_order(self, audit_log: AuditLog):
        for i in range(5):
            audit_log.append(AuditEntry(event="executed", amount=float(i + 1), description=f"item {i}", band=Band.L2))
        entries = list(audit_log.read_all())
        assert len(entries) == 5
        for i, e in enumerate(entries):
            assert e.amount == float(i + 1)

    def test_empty_log_returns_nothing(self, audit_log: AuditLog):
        entries = list(audit_log.read_all())
        assert entries == []

    def test_nonexistent_file_returns_nothing(self, tmp_path: Path):
        log = AuditLog(tmp_path / "nonexistent" / "log.jsonl")
        entries = list(log.read_all())
        assert entries == []


class TestTail:
    def test_tail_returns_most_recent_first(self, audit_log: AuditLog):
        for i in range(5):
            audit_log.append(AuditEntry(event="executed", amount=float(i + 1), description=f"item {i}", band=Band.L2))
        recent = audit_log.tail(limit=3)
        assert len(recent) == 3
        assert recent[0].amount == 5.0
        assert recent[1].amount == 4.0
        assert recent[2].amount == 3.0

    def test_tail_from_empty_log(self, audit_log: AuditLog):
        assert audit_log.tail(limit=10) == []

    def test_tail_with_limit_larger_than_count(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="executed", amount=1.0, description="one", band=Band.L2))
        recent = audit_log.tail(limit=100)
        assert len(recent) == 1


class TestFilterByEvent:
    def test_filter_by_event(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="executed", amount=10.0, description="spend", band=Band.L2))
        audit_log.append(AuditEntry(event="denied", amount=0.0, description="denied", band=Band.L2))
        audit_log.append(AuditEntry(event="executed", amount=20.0, description="another", band=Band.L2))
        executed = audit_log.filter_by_event("executed")
        assert len(executed) == 2
        denied = audit_log.filter_by_event("denied")
        assert len(denied) == 1

    def test_filter_no_match(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="executed", amount=1.0, description="test", band=Band.L2))
        assert audit_log.filter_by_event("escalated") == []


class TestTotalSpent:
    def test_total_spent_all(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="executed", amount=10.0, description="a", band=Band.L2, approved_by="Alice"))
        audit_log.append(AuditEntry(event="executed", amount=20.0, description="b", band=Band.L2))
        assert audit_log.total_spent() == 30.0

    def test_total_spent_autonomous_only(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="executed", amount=10.0, description="approved", band=Band.L2, approved_by="Alice"))
        audit_log.append(AuditEntry(event="executed", amount=20.0, description="autonomous", band=Band.L2))
        assert audit_log.total_spent(autonomous_only=True) == 20.0

    def test_total_spent_approved_only(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="executed", amount=10.0, description="approved", band=Band.L2, approved_by="Alice"))
        audit_log.append(AuditEntry(event="executed", amount=20.0, description="autonomous", band=Band.L2))
        assert audit_log.total_spent(approved_only=True) == 10.0

    def test_total_spent_rounds_to_two_decimals(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="executed", amount=10.005, description="precise", band=Band.L2))
        assert audit_log.total_spent() == 10.01

    def test_total_spent_ignores_non_executed(self, audit_log: AuditLog):
        audit_log.append(AuditEntry(event="escalated", amount=100.0, description="never executed", band=Band.L2))
        assert audit_log.total_spent() == 0.0

    def test_total_spent_empty_log(self, audit_log: AuditLog):
        assert audit_log.total_spent() == 0.0


class TestErrorHandling:
    def test_append_to_readonly_dir_fails(self):
        log = AuditLog(Path("/dev/null/audit.jsonl"))
        entry = AuditEntry(event="executed", amount=1.0, description="test", band=Band.L2)
        with pytest.raises(AuditWriteError):
            log.append(entry)
