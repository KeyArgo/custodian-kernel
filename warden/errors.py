"""Warden exception hierarchy.

Every error message in this module is written to be safe to show to an
agent: no error ever includes a secret value, a vault key, or the
plaintext of any entry.
"""
from __future__ import annotations


class WardenError(Exception):
    """Base class for all Warden errors."""


class VaultMissingError(WardenError):
    """No vault exists at the given path — run ``warden init`` first."""


class VaultLockedError(WardenError):
    """The vault could not be unlocked (wrong passphrase/keyfile, or the
    ciphertext failed authentication)."""


class VaultCorruptError(WardenError):
    """The vault file exists but is not a valid Warden vault (truncated,
    tampered with, or not a vault at all)."""


class UnknownRefError(WardenError):
    """The requested secret ref does not exist in the vault."""


class GrantDeniedError(WardenError):
    """The requester holds no grant covering this ref (or the grant's
    band ceiling is below the requested band)."""


class AuditChainBrokenError(WardenError):
    """The audit log's hash chain does not verify — records were
    altered, reordered, or truncated after being written."""


class CryptoUnavailableError(WardenError):
    """The ``cryptography`` package is not installed. Install with
    ``pip install custodian-kernel[warden]``."""
