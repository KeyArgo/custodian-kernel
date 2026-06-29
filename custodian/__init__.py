"""Custodian: a kernel-enforced authority and spend platform for AI agents.

The core property: an agent can be trusted with a real, bounded budget and
real-world authority because the boundary is enforced outside the agent's
own process (NemoClaw kernel sandbox, Landlock+OPA) and outside the agent's
own code path (privilege separation between request and approval), not
because the agent promises to behave.
"""
from custodian.types import (
    AuditEntry,
    AuthorityState,
    Band,
    Decision,
    PendingApproval,
    SpendRequest,
    Verdict,
)

__version__ = "0.1.1"

__all__ = [
    "__version__",
    "Band",
    "AuthorityState",
    "SpendRequest",
    "Verdict",
    "Decision",
    "PendingApproval",
    "AuditEntry",
]
