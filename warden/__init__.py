"""Warden — a credential broker for AI agents.

Warden is deliberately a *separate* package from the Custodian kernel.
Custodian decides whether an action is allowed; Warden decides whether a
credential may be materialized for that action — and materializes it in a
way the agent process never observes.

The core contract:

* Secrets live in an encrypted vault (AES-256-GCM, scrypt KDF).
  Plaintext never touches disk; entry names are encrypted along with
  values, so even the *inventory* of secrets is not readable at rest.
* The agent only ever holds a ``SecretRef`` (``warden://<name>``) — a
  zero-value pointer that is safe to log, print, or hand to a model.
* Resolution happens at *egress*: the broker injects real values into a
  subprocess environment (or a NemoClaw sandbox) at the last possible
  moment, gated by an explicit grant policy.
* Every resolve/deny is recorded in a hash-chained, HMAC-signed audit
  log. Truncation or edits break the chain and are detected.

Humans manage the vault like a password manager::

    warden init
    warden add stripe_sk            # value prompted, never echoed
    warden list                     # names + metadata, never values
    warden grant stripe_sk --to skill:stripe-spend --max-band L2
    warden exec --with stripe_sk=STRIPE_SECRET_KEY -- python agent.py

Agents get exactly one verb — ``resolve`` — and only through the broker,
only for refs they hold a grant for, and only into an egress channel.
"""

from warden.refs import SecretRef
from warden.errors import (
    WardenError,
    VaultLockedError,
    VaultMissingError,
    VaultCorruptError,
    GrantDeniedError,
    UnknownRefError,
)
from warden.vault import Vault
from warden.broker import Broker
from warden.grants import Grant, GrantPolicy

__all__ = [
    "SecretRef",
    "Vault",
    "Broker",
    "Grant",
    "GrantPolicy",
    "WardenError",
    "VaultLockedError",
    "VaultMissingError",
    "VaultCorruptError",
    "GrantDeniedError",
    "UnknownRefError",
]

__version__ = "0.1.0"
