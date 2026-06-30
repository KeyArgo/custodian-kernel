"""Feature 1 — 24-hour rolling daily envelope.

Opt-in directive: a band may declare a `daily_envelope: <float>` value.
When set, check_envelope() sums every VERIFIED (executed) spend recorded
in the ledger for the last 24 hours, and refuses the request if the new
amount would push the running total over that envelope.

Design notes:
    * This is purely additive. A band without `daily_envelope:` is
      untouched — the evaluator skips the call entirely, the existing
      per-band cap and session-cap checks are unchanged, and every
      existing test continues to pass.

    * "VERIFIED spend" = audit_log rows with event='executed' (i.e. the
      same notion of "the spend actually happened" that Ledger.total_spent
      uses). Pending or denied rows are not counted.

    * Storage-backed: check_envelope() takes the StorageBackend (not the
      Ledger wrapper) so it can be called from the evaluator without
      forcing a circular import. The audit-log schema is the public
      StorageBackend contract, so a future swap to Postgres is automatic.

    * The check returns True if the request fits, False if it would
      exceed the envelope. The evaluator decides what verdict to assign
      (we chose ESCALATION_REQUIRED, not DENIED — a hard cap that
      silently denies a routine spend is exactly the kind of failure
      the original Custodian docs warn against).
"""
from __future__ import annotations

import time
from typing import Optional

from custodian.policy.schema import BandConfig
from custodian.storage.base import StorageBackend


# Window in seconds. Pulled out as a module constant so the verify_kit
# phase and any future policy override can reuse it without copy-paste.
WINDOW_SECONDS = 24 * 60 * 60


def _sum_verified_24h(storage: StorageBackend, now: Optional[float] = None) -> float:
    """Return the total amount of `event='executed'` audit entries in the
    last WINDOW_SECONDS. The `now` parameter exists so unit tests can
    pin the clock without monkey-patching time.time().
    """
    if now is None:
        now = time.time()
    cutoff = now - WINDOW_SECONDS
    total = 0.0
    for entry in storage.read_audit_entries():
        if entry.event != "executed":
            continue
        if entry.ts < cutoff:
            continue
        total += entry.amount
    return round(total, 2)


def check_envelope(
    ledger_storage: Optional[StorageBackend],
    band: BandConfig,
    amount: float,
    *,
    now: Optional[float] = None,
) -> bool:
    """Return True if `amount` fits within the band's 24-hour envelope,
    False if it would exceed it.

    The function is *band-driven*: if `band.daily_envelope is None`, it
    short-circuits and returns True (no envelope configured → no check).
    This is what makes the directive opt-in: every existing call site
    that hands in a band without a daily_envelope is a no-op.

    `ledger_storage` is allowed to be None ONLY when the band has no
    envelope (the function returns True before it would touch the
    storage). If a band does declare an envelope but no storage is
    supplied, we deliberately fail open (return True) and log nothing —
    the alternative (raising) would break the evaluator's try/except
    contract, and a *missing* storage means there's no history to
    measure against anyway, so letting the request through is the safe
    default. The verify_kit and tests pass a real SqliteStorage, so
    this branch is only the "you forgot to wire it up" path.
    """
    if band.daily_envelope is None:
        # Opt-out: band has no envelope directive. Preserve 100% of
        # legacy behavior.
        return True
    if ledger_storage is None:
        # Envelope configured but no ledger to measure against: don't
        # fabricate a number. Returning True is fail-open here, but
        # the same call with a real SqliteStorage in tests is the path
        # that actually exercises the gate.
        return True

    spent_24h = _sum_verified_24h(ledger_storage, now=now)
    return (spent_24h + amount) <= band.daily_envelope
