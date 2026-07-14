"""Caduceus exception hierarchy.

Every error message in this module is written to be safe to show to an
agent: no error ever includes a secret value, a vault key, or the
plaintext of any entry.
"""
from __future__ import annotations


class CaduceusError(Exception):
    """Base class for all Caduceus errors."""


class VaultMissingError(CaduceusError):
    """No vault exists at the given path — run ``caduceus init`` first."""


class VaultLockedError(CaduceusError):
    """The vault could not be unlocked (wrong passphrase/keyfile, or the
    ciphertext failed authentication)."""


class VaultCorruptError(CaduceusError):
    """The vault file exists but is not a valid Caduceus vault (truncated,
    tampered with, or not a vault at all)."""


class UnknownRefError(CaduceusError):
    """The requested secret ref does not exist in the vault."""


class GrantDeniedError(CaduceusError):
    """The requester holds no grant covering this ref (or the grant's
    band ceiling is below the requested band)."""


class AuditChainBrokenError(CaduceusError):
    """The audit log's hash chain does not verify — records were
    altered, reordered, or truncated after being written."""


class CryptoUnavailableError(CaduceusError):
    """The ``cryptography`` package is not installed. Install with
    ``pip install custodian-kernel[caduceus]``."""
