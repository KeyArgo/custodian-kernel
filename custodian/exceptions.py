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


class NemoClawError(CustodianError):
    """Base class for NemoClaw sandbox adapter errors.

    Exists so a caller can distinguish "the sandbox infrastructure itself
    is broken" from "the governed script ran and failed on its own terms" —
    prior to this, both looked like the same opaque subprocess stderr blob.
    """


class SandboxGatewayDownError(NemoClawError):
    """The NemoClaw sandbox gateway is unreachable (transport/connection
    failure reaching the sandbox), not a failure of the script being run.
    Recoverable via `nemohermes <sandbox> status` or `recover`."""


class SandboxTimeoutError(NemoClawError):
    """The sandboxed command did not complete within the given timeout."""


class SandboxScriptError(NemoClawError):
    """The sandbox itself was reachable and the script ran, but exited
    non-zero for its own reasons (a real traceback, a real validation
    failure). Only raised when the caller opts in via `run(..., check=True)`
    — by default `run()` returns this as a non-ok ExecResult instead, since
    an ordinary script failure is meaningful data the caller usually wants
    to inspect (e.g. render to a demo UI), not an exception to catch."""


class ToolSandboxUnavailableError(CustodianError):
    """A governed skill script cannot be run because filesystem/exec
    confinement (bwrap + unprivileged user namespaces) is unavailable on
    this host and CUSTODIAN_ALLOW_UNSANDBOXED_TOOLS was not set. Raised by
    custodian.tools.registry.CustodianTool.invoke() -- fail closed rather
    than run a governed script with full ambient filesystem access."""
