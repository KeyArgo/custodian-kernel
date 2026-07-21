"""Paladin exception hierarchy.

Every error message in this module is written to be safe to show to an
agent: no error ever includes a secret value, a vault key, or the
plaintext of any entry.
"""
from __future__ import annotations


class PaladinError(Exception):
    """Base class for all Paladin errors."""


class VaultMissingError(PaladinError):
    """No vault exists at the given path — run ``paladin init`` first."""


class VaultLockedError(PaladinError):
    """The vault could not be unlocked (wrong passphrase/keyfile, or the
    ciphertext failed authentication)."""


class VaultCorruptError(PaladinError):
    """The vault file exists but is not a valid Paladin vault (truncated,
    tampered with, or not a vault at all)."""


class UnknownRefError(PaladinError):
    """The requested secret ref does not exist in the vault."""


class GrantDeniedError(PaladinError):
    """The requester holds no grant covering this ref (or the grant's
    band ceiling is below the requested band)."""


class AuditChainBrokenError(PaladinError):
    """The audit log's hash chain does not verify — records were
    altered, reordered, or truncated after being written."""


class CryptoUnavailableError(PaladinError):
    """The ``cryptography`` package is not installed. Install with
    ``pip install custodian-kernel[paladin]``."""


class EgressDeniedError(PaladinError):
    """A sandboxed egress request was refused before the credential was
    ever resolved: the target host/method/path fell outside the entry's
    ``allowed_hosts`` ceiling or the grant's scope, or the child named a
    ref outside its per-run allow-list. Value-free by construction."""


class SandboxUnavailableError(PaladinError):
    """The hardened, network-isolated egress sandbox cannot be built here
    (``bwrap`` missing, or unprivileged user namespaces are disabled by
    the kernel). Paladin refuses rather than silently falling back to
    plaintext-env injection — pass ``allow_unsandboxed=True`` to opt into
    the weaker path explicitly."""
