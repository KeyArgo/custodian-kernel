"""Abstract storage-backend interface.

A storage backend provides persistence for the three things the authority
engine needs to survive restarts: the current authority state (one row),
the append-only audit log (rows), and the current pending-approval record
(at most one row). Every operation is a full read or write -- the backend
is not expected to maintain in-memory state across calls.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from custodian.types import AuditEntry, AuthorityState, PendingApproval


class StorageBackend(ABC):
    @abstractmethod
    def load_authority_state(self) -> Optional[AuthorityState]:
        """Load the current authority state, or None if none exists."""

    @abstractmethod
    def save_authority_state(self, state: AuthorityState) -> None:
        """Persist (upsert) the authority state."""

    @abstractmethod
    def append_audit_entry(self, entry: AuditEntry) -> None:
        """Append one audit entry. The backend assigns the timestamp."""

    @abstractmethod
    def read_audit_entries(self, limit: Optional[int] = None) -> list[AuditEntry]:
        """Return audit entries in insertion order (oldest first)."""

    @abstractmethod
    def get_pending_approval(self) -> Optional[PendingApproval]:
        """Return the current pending approval, or None."""

    @abstractmethod
    def set_pending_approval(self, approval: PendingApproval) -> None:
        """Set (upsert) the pending-approval record."""

    @abstractmethod
    def clear_pending_approval(self) -> None:
        """Remove any pending-approval record."""
