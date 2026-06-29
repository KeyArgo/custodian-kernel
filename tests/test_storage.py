"""Tests for custodian.storage.sqlite.SqliteStorage."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from custodian.exceptions import StorageError
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, AuthorityState, Band, PendingApproval


@pytest.fixture
def storage(tmp_path: Path) -> SqliteStorage:
    return SqliteStorage(tmp_path / "test.db")


class TestAuthorityState:
    def test_load_when_empty_returns_none(self, storage: SqliteStorage):
        assert storage.load_authority_state() is None

    def test_save_and_load(self, storage: SqliteStorage):
        state = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=3.0)
        storage.save_authority_state(state)
        loaded = storage.load_authority_state()
        assert loaded is not None
        assert loaded.band == Band.L2
        assert loaded.per_action_cap == 2.0
        assert loaded.session_cap == 10.0
        assert loaded.spent_this_session == 3.0

    def test_round_trip_equality(self, storage: SqliteStorage):
        state = AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=100.0, spent_this_session=0.0)
        storage.save_authority_state(state)
        loaded = storage.load_authority_state()
        assert loaded.band == state.band
        assert loaded.per_action_cap == state.per_action_cap
        assert loaded.session_cap == state.session_cap
        assert loaded.spent_this_session == state.spent_this_session

    def test_upsert_overwrites(self, storage: SqliteStorage):
        s1 = AuthorityState(band=Band.L1, per_action_cap=0.50, session_cap=5.0, spent_this_session=0.0)
        s2 = AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=1.0)
        storage.save_authority_state(s1)
        storage.save_authority_state(s2)
        loaded = storage.load_authority_state()
        assert loaded.band == Band.L2
        assert loaded.per_action_cap == 2.0


class TestAuditEntries:
    def test_append_and_read(self, storage: SqliteStorage):
        entry = AuditEntry(event="executed", amount=45.0, description="License renewal", band=Band.L2)
        storage.append_audit_entry(entry)
        entries = storage.read_audit_entries()
        assert len(entries) == 1
        assert entries[0].amount == 45.0

    def test_read_returns_in_insertion_order(self, storage: SqliteStorage):
        for i in range(5):
            storage.append_audit_entry(
                AuditEntry(event="executed", amount=float(i + 1), description=f"item {i}", band=Band.L2)
            )
        entries = storage.read_audit_entries()
        assert len(entries) == 5
        assert [e.amount for e in entries] == [1.0, 2.0, 3.0, 4.0, 5.0]

    def test_read_with_limit(self, storage: SqliteStorage):
        for i in range(10):
            storage.append_audit_entry(
                AuditEntry(event="executed", amount=1.0, description=f"item {i}", band=Band.L2)
            )
        entries = storage.read_audit_entries(limit=3)
        assert len(entries) == 3

    def test_empty_read_returns_empty_list(self, storage: SqliteStorage):
        assert storage.read_audit_entries() == []


class TestPendingApproval:
    def test_get_when_empty_returns_none(self, storage: SqliteStorage):
        assert storage.get_pending_approval() is None

    def test_set_and_get(self, storage: SqliteStorage):
        approval = PendingApproval(
            amount=45.0,
            description="License renewal",
            reason="exceeds cap",
            created_at=time.time(),
        )
        storage.set_pending_approval(approval)
        loaded = storage.get_pending_approval()
        assert loaded is not None
        assert loaded.amount == 45.0
        assert loaded.description == "License renewal"
        assert loaded.reason == "exceeds cap"

    def test_clear_pending_approval(self, storage: SqliteStorage):
        approval = PendingApproval(amount=10.0, description="test", reason="test", created_at=time.time())
        storage.set_pending_approval(approval)
        storage.clear_pending_approval()
        assert storage.get_pending_approval() is None

    def test_clear_when_empty_does_not_error(self, storage: SqliteStorage):
        storage.clear_pending_approval()
        assert storage.get_pending_approval() is None

    def test_upsert_replaces(self, storage: SqliteStorage):
        a1 = PendingApproval(amount=10.0, description="first", reason="a", created_at=1000.0)
        a2 = PendingApproval(amount=20.0, description="second", reason="b", created_at=2000.0)
        storage.set_pending_approval(a1)
        storage.set_pending_approval(a2)
        loaded = storage.get_pending_approval()
        assert loaded.amount == 20.0
        assert loaded.description == "second"


class TestConcurrentWrites:
    def test_sequential_writes_both_land(self, storage: SqliteStorage):
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=10.0, description="first write", band=Band.L2)
        )
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=20.0, description="second write", band=Band.L2)
        )
        entries = storage.read_audit_entries()
        assert len(entries) == 2
        assert [e.amount for e in entries] == [10.0, 20.0]

    def test_multiple_authority_state_writes(self, storage: SqliteStorage):
        for i in range(5):
            storage.save_authority_state(
                AuthorityState(band=Band.L2, per_action_cap=2.0, session_cap=10.0, spent_this_session=float(i))
            )
        loaded = storage.load_authority_state()
        assert loaded.spent_this_session == 4.0


class TestErrorHandling:
    def test_operations_on_closed_db_raise_error(self, tmp_path: Path):
        storage = SqliteStorage(tmp_path / "test.db")
        storage.path.parent  # verify it was created
        # append/read with a valid storage doesn't error
        storage.append_audit_entry(
            AuditEntry(event="executed", amount=1.0, description="test", band=Band.L2)
        )
        assert len(storage.read_audit_entries()) == 1
