"""Paladin — a credential broker for AI agents.

Paladin is deliberately a *separate* package from the Custodian kernel.
Custodian decides whether an action is allowed; Paladin decides whether a
credential may be materialized for that action — and materializes it in a
way the agent process never observes.

The core contract:

* Secrets live in an encrypted vault (AES-256-GCM, scrypt KDF).
  Plaintext never touches disk; entry names are encrypted along with
  values, so even the *inventory* of secrets is not readable at rest.
* The agent only ever holds a ``SecretRef`` (``paladin://<name>``) — a
  zero-value pointer that is safe to log, print, or hand to a model.
* Resolution happens at *egress*: the broker injects real values into a
  subprocess environment (or a NemoClaw sandbox) at the last possible
  moment, gated by an explicit grant policy.
* Every resolve/deny is recorded in a hash-chained, HMAC-signed audit
  log. Truncation or edits break the chain and are detected.

Humans manage the vault like a password manager::

    paladin init
    paladin add stripe_sk            # value prompted, never echoed
    paladin list                     # names + metadata, never values
    paladin grant stripe_sk --to skill:stripe-spend --max-band L2
    paladin exec --with stripe_sk=STRIPE_SECRET_KEY -- python agent.py

Agents get exactly one verb — ``resolve`` — and only through the broker,
only for refs they hold a grant for, and only into an egress channel.
"""

from paladin.refs import SecretRef
from paladin.errors import (
    PaladinError,
    VaultLockedError,
    VaultMissingError,
    VaultCorruptError,
    GrantDeniedError,
    UnknownRefError,
)
from paladin.vault import Vault
from paladin.broker import Broker
from paladin.grants import Grant, GrantPolicy

__all__ = [
    "SecretRef",
    "Vault",
    "Broker",
    "Grant",
    "GrantPolicy",
    "PaladinError",
    "VaultLockedError",
    "VaultMissingError",
    "VaultCorruptError",
    "GrantDeniedError",
    "UnknownRefError",
]

__version__ = "0.1.0"
