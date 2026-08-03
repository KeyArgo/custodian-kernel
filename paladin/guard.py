"""Value-free Paladin integrity guard for credential operations."""
from __future__ import annotations

from dataclasses import dataclass

from paladin.audit import AuditLog
from paladin.errors import PaladinError
from paladin.grants import OWNER_REQUESTERS


class IntegrityGuardError(PaladinError):
    """Audit integrity is failed; agent credential authority is suspended."""


@dataclass(frozen=True)
class IntegrityStatus:
    healthy: bool
    valid_records: int
    problem: str = ""


class PaladinGuard:
    """Verify audit evidence before an AI receives credential authority.

    Human owners retain a recovery path; non-owner requesters fail closed.
    This guard never resolves or displays a secret value.
    """
    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    def status(self) -> IntegrityStatus:
        try:
            return IntegrityStatus(True, self.audit.verify())
        except Exception as exc:
            # Audit errors are intentionally summarized; records themselves
            # remain inspectable through the value-free audit command.
            return IntegrityStatus(False, 0, str(exc))

    def require_agent_safe(self, requester: str) -> None:
        if requester in OWNER_REQUESTERS:
            return
        status = self.status()
        if not status.healthy:
            raise IntegrityGuardError(
                "Paladin Guard blocked credential authority: audit integrity failed; "
                "operator recovery is required")
