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

from custodian.types import AuditEntry, AuthorityState, KillSwitchState, PendingApproval


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

    @abstractmethod
    def get_kill_switch(self) -> KillSwitchState:
        """Return the current kill-switch state. Never None -- defaults to
        not-killed if nothing has been set yet, so callers don't need a
        separate existence check before consulting it on every decision."""

    @abstractmethod
    def set_kill_switch(self, state: KillSwitchState) -> None:
        """Persist (upsert) the kill-switch state. This is the one write
        path any control surface -- our CLI, our dashboard, or someone
        else's -- uses to engage or release the kill switch. The engine
        itself never calls this; only an operator action does."""
