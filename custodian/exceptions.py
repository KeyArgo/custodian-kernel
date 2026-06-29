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


class BackendError(CustodianError):
    """Base class for approval-backend errors (e.g. TwilioVerifyBackend)."""


class BackendConfigurationError(BackendError):
    """The backend is missing required configuration (e.g. secrets)."""


class AuditWriteError(CustodianError):
    """The append-only audit log could not be written."""


class StorageError(CustodianError):
    """Base class for storage backend errors."""


class ConfigError(CustodianError):
    """Custodian's own configuration is invalid or incomplete."""
