"""Typed exception hierarchy for Custodian.

Every failure mode that matters for an agent-authority platform gets its own
type, not a bare Exception, so a developer's except clauses can be precise
about what they're actually handling.
"""


class CustodianError(Exception):
    """Base class for all Custodian errors."""


class PolicyError(CustodianError):
    """Base class for policy loading/validation/evaluation errors."""


class PolicyValidationError(PolicyError):
    """The policy file failed schema validation."""


class PolicyNotFoundError(PolicyError):
    """No policy file found at the given path."""


class BandExceededError(CustodianError):
    """A spend request exceeds the current authority band's limits.

    This is not itself an error condition for the engine — it's the trigger
    for escalation — but callers that expect autonomous execution and get
    this instead need a precise signal, not a bare exception.
    """

    def __init__(self, amount: float, cap: float, reason: str):
        self.amount = amount
        self.cap = cap
        self.reason = reason
        super().__init__(reason)


class EscalationError(CustodianError):
    """Base class for errors in the human-approval escalation flow."""


class NoPendingApprovalError(EscalationError):
    """approve.py or deny.py was invoked but there is no pending escalation."""


class ApprovalExpiredError(EscalationError):
    """The pending approval's TTL elapsed before a human responded."""


class ApprovalCodeRejectedError(EscalationError):
    """The human-supplied code was rejected by the verification backend
    (wrong code, already used, or expired at the backend's own TTL)."""


class BackendError(CustodianError):
    """Base class for approval-backend (Twilio, Slack, email, ...) errors."""


class BackendConfigurationError(BackendError):
    """The backend is missing required configuration (e.g. secrets)."""


class ExecutionError(CustodianError):
    """The underlying real-world action (e.g. the Stripe call) failed."""


class AuditWriteError(CustodianError):
    """The append-only audit log could not be written."""


class StorageError(CustodianError):
    """Base class for storage backend errors."""


class ConfigError(CustodianError):
    """Custodian's own configuration is invalid or incomplete."""
