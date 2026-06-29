"""The Ledger: a convenience layer over a StorageBackend for spend recording,
budget queries, and remaining-budget calculations.

Wraps a StorageBackend (not AuditLog) so all persistence goes through one
abstraction. Delegates to the backend for reads/writes rather than
duplicating the filtering logic from AuditLog -- the Ledger is a thin
orchestrator, not a second implementation of the same queries.
"""
from __future__ import annotations

from typing import Optional

from custodian.storage.base import StorageBackend
from custodian.types import AuditEntry, AuthorityState


class Ledger:
    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def record_spend(self, entry: AuditEntry) -> None:
        self.storage.append_audit_entry(entry)

    def total_spent(
        self, *, autonomous_only: bool = False, approved_only: bool = False,
    ) -> float:
        total = 0.0
        for entry in self.storage.read_audit_entries():
            if entry.event != "executed":
                continue
            if autonomous_only and entry.approved_by:
                continue
            if approved_only and not entry.approved_by:
                continue
            total += entry.amount
        return round(total, 2)

    def remaining_budget(self, state: AuthorityState) -> float:
        return state.remaining_session_budget()
