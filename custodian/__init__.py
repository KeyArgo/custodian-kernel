"""Custodian: a kernel-enforced authority and spend platform for AI agents.

The core property: an agent can be trusted with a real, bounded budget and
real-world authority because the boundary is enforced outside the agent's
own process (NemoClaw kernel sandbox, Landlock+OPA) and outside the agent's
own code path (privilege separation between request and approval), not
because the agent promises to behave.

0.2.0 — kernel as fabric:
  @govern decorator      wraps any function with implicit kernel enforcement
  CustodianMiddleware    ASGI middleware for FastAPI/Flask/Starlette
  CustodianSession       context manager with sub-session band inheritance
  GovernedReceipt        SHA-256 verifiable proof artifact for every action
  EventBus               pub/sub hooks for kernel lifecycle events
"""
from custodian.types import (
    AuditEntry,
    AuthorityState,
    Band,
    Decision,
    PendingApproval,
    SpendRequest,
    Verdict,
    _SECRET_SENTINELS,
    _is_secret_key,
    sanitize_dict,
)
from custodian.govern import govern, GovernedResult, EscalationRequired, KernelDenied
from custodian.session import CustodianSession
from custodian.receipt import GovernedReceipt
from custodian.bus import on as on_event, emit as emit_event
from custodian.middleware import CustodianMiddleware
from custodian.client import (
    ValueFreeClient,
    ValueFreePlan,
    ValueFreeResult,
    KernelDenied as ValueFreeKernelDenied,
)

__version__ = "0.2.1"

__all__ = [
    "__version__",
    # Core types (0.1.x)
    "Band",
    "AuthorityState",
    "SpendRequest",
    "Verdict",
    "Decision",
    "PendingApproval",
    "AuditEntry",
    # 0.2.0 — kernel as fabric
    "govern",
    "GovernedResult",
    "EscalationRequired",
    "KernelDenied",
    "CustodianSession",
    "GovernedReceipt",
    "CustodianMiddleware",
    "on_event",
    "emit_event",
    # 0.2.1 — value-free protocol + tamper-snapshot
    "_SECRET_SENTINELS",
    "_is_secret_key",
    "sanitize_dict",
    "ValueFreeClient",
    "ValueFreePlan",
    "ValueFreeResult",
    "ValueFreeKernelDenied",
]
