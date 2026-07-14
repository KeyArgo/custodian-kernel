"""Grant policy: which requester may resolve which secret, up to which band.

A requester is a namespaced identity string:

* ``skill:stripe-spend``   — a Hermes/Custodian skill by name
* ``adapter:spend-sentinel`` — a Custodian adapter
* ``sandbox:hermes-hackathon`` — a NemoClaw sandbox
* ``user:cli``             — the human at the Warden CLI

Deny-by-default: with no matching grant, resolution fails. Wildcards are
allowed only in the *ref* position (``stripe/*``), never for requesters —
you always say exactly *who* gets a secret.

Grants live inside the encrypted vault, so the policy itself is neither
readable nor forgeable at rest.
"""
from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from warden.errors import GrantDeniedError, WardenError

# Custodian authority bands, lowest to highest.
BAND_ORDER = ["L0", "L1", "L2", "L3", "L4"]


def band_index(band: str) -> int:
    try:
        return BAND_ORDER.index(band)
    except ValueError:
        raise WardenError(f"unknown band {band!r} (expected one of {BAND_ORDER})")


@dataclass
class Grant:
    """Permission for one requester to resolve refs matching a pattern."""

    ref_pattern: str            # exact name or fnmatch pattern: "stripe/*"
    requester: str              # exact namespaced id — no wildcards
    max_band: str = "L2"        # resolution denied above this band
    expires_at: Optional[float] = None  # unix time; None = no expiry
    note: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if ":" not in self.requester or "*" in self.requester:
            raise WardenError(
                f"requester must be an exact 'namespace:name' id, got {self.requester!r}"
            )
        band_index(self.max_band)  # validate

    def matches(self, ref_name: str, requester: str, band: str) -> bool:
        if requester != self.requester:
            return False
        if self.expires_at is not None and time.time() > self.expires_at:
            return False
        if band_index(band) > band_index(self.max_band):
            return False
        return fnmatch.fnmatchcase(ref_name, self.ref_pattern)


# Requesters that hold an implicit all-refs grant: the human at the CLI has
# already proven possession of the vault master key, which could mint any
# grant anyway — requiring a self-grant would be ceremony, not security.
# Agent-side requesters (skill:/adapter:/sandbox:) are NEVER implicit.
OWNER_REQUESTERS = frozenset({"user:cli"})


class GrantPolicy:
    """The grant table, backed by the vault's encrypted grants blob."""

    def __init__(self, vault) -> None:
        self._vault = vault
        self._grants = [Grant(**g) for g in vault.raw_grants]

    def list(self) -> list[Grant]:
        return list(self._grants)

    def grant(self, ref_pattern: str, requester: str, max_band: str = "L2",
              ttl_seconds: Optional[float] = None, note: str = "") -> Grant:
        g = Grant(
            ref_pattern=ref_pattern, requester=requester, max_band=max_band,
            expires_at=(time.time() + ttl_seconds) if ttl_seconds else None,
            note=note,
        )
        self._grants.append(g)
        self._persist()
        return g

    def revoke(self, ref_pattern: str, requester: str) -> int:
        """Remove all grants exactly matching (pattern, requester).
        Returns how many were removed."""
        before = len(self._grants)
        self._grants = [
            g for g in self._grants
            if not (g.ref_pattern == ref_pattern and g.requester == requester)
        ]
        removed = before - len(self._grants)
        if removed:
            self._persist()
        return removed

    def check(self, ref_name: str, requester: str, band: str = "L0") -> Grant:
        """Return the grant authorizing this access, or raise GrantDeniedError.

        The error message is agent-safe: it names the ref and requester
        (both value-free) but reveals nothing about the vault contents.
        """
        if requester in OWNER_REQUESTERS:
            return Grant(ref_pattern="*", requester=requester, max_band="L4",
                         note="implicit owner grant")
        for g in self._grants:
            if g.matches(ref_name, requester, band):
                return g
        raise GrantDeniedError(
            f"requester {requester!r} holds no grant for ref {ref_name!r} at band {band}"
        )

    def _persist(self) -> None:
        self._vault.set_raw_grants([asdict(g) for g in self._grants])
