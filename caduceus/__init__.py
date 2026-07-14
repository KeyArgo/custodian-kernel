"""Caduceus — a credential broker for AI agents.

Caduceus is deliberately a *separate* package from the Custodian kernel.
Custodian decides whether an action is allowed; Caduceus decides whether a
credential may be materialized for that action — and materializes it in a
way the agent process never observes.

The core contract:

* Secrets live in an encrypted vault (AES-256-GCM, scrypt KDF).
  Plaintext never touches disk; entry names are encrypted along with
  values, so even the *inventory* of secrets is not readable at rest.
* The agent only ever holds a ``SecretRef`` (``caduceus://<name>``) — a
  zero-value pointer that is safe to log, print, or hand to a model.
* Resolution happens at *egress*: the broker injects real values into a
  subprocess environment (or a NemoClaw sandbox) at the last possible
  moment, gated by an explicit grant policy.
* Every resolve/deny is recorded in a hash-chained, HMAC-signed audit
  log. Truncation or edits break the chain and are detected.

Humans manage the vault like a password manager::

    caduceus init
    caduceus add stripe_sk            # value prompted, never echoed
    caduceus list                     # names + metadata, never values
    caduceus grant stripe_sk --to skill:stripe-spend --max-band L2
    caduceus exec --with stripe_sk=STRIPE_SECRET_KEY -- python agent.py

Agents get exactly one verb — ``resolve`` — and only through the broker,
only for refs they hold a grant for, and only into an egress channel.
"""

from caduceus.refs import SecretRef
from caduceus.errors import (
    CaduceusError,
    VaultLockedError,
    VaultMissingError,
    VaultCorruptError,
    GrantDeniedError,
    UnknownRefError,
)
from caduceus.vault import Vault
from caduceus.broker import Broker
from caduceus.grants import Grant, GrantPolicy

__all__ = [
    "SecretRef",
    "Vault",
    "Broker",
    "Grant",
    "GrantPolicy",
    "CaduceusError",
    "VaultLockedError",
    "VaultMissingError",
    "VaultCorruptError",
    "GrantDeniedError",
    "UnknownRefError",
]

__version__ = "0.1.0"
