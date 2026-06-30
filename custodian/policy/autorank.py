"""Feature 3 — Auto-downgrade after task.

Opt-in directive: a band may declare `band_after_task: <Band>`. When
set, the next request from the same agent (within 60 seconds of a
successful VERIFIED request against this band) is resolved against
`band_after_task` instead of the original band.

Design notes:
    * The downgrade table is a process-local dict keyed by
      agent_id → (effective_band, expires_at). A 60-second TTL is
      hard-coded per the design spec — short enough that a stuck
      downgrade is a near-impossible failure mode, long enough that
      legitimate follow-up requests from the same agent are caught.

    * apply_autorank() is the pure resolution function:
      "given a state and a band, what band should I actually use?"
      It does NOT mutate state on success — that would be a side
      effect tangled into a decision function. The act of recording
      a successful spend is owned by the caller (the executor that
      ran the request), not by the policy evaluator. We provide
      record_successful_request() as the dedicated side-effect
      function so test code can call it explicitly and verify the
      table transitions cleanly.

    * Truly opt-in. If the band has no `band_after_task` directive,
      apply_autorank() returns the input band unchanged and the
      downgrade table is never read. The record_* functions are
      no-ops when the policy has no band_after_task on any band.

    * The dict is module-level on purpose — it's a per-process
      cache of "recently completed tasks", which is exactly the
      lifetime where it makes sense. A real deployment would persist
      this to the authority_state row or a small `downgrade` table;
      the in-memory dict keeps the feature testable in isolation
      without forcing a schema migration on the storage layer.
"""
from __future__ import annotations

import time
from typing import Optional

from custodian.policy.schema import BandConfig
from custodian.types import Band


# Spec-defined TTL: a downgrade is good for 60 seconds after a
# successful request. Short enough that a stale downgrade clears
# itself before any human notices, long enough that an agent's
# immediate follow-up request is correctly re-routed.
DOWNGRADE_TTL_SECONDS = 60

# Per-process downgrade table. Cleared on process restart by
# definition (in-memory dict), which is consistent with the
# "this only affects the next request from the same agent"
# semantics — a fresh process has no "previous request" to
# remember.
_downgrade_table: dict[str, tuple[Band, float]] = {}


def _purge_expired(now: float) -> None:
    """Drop entries whose TTL has elapsed. Called on every lookup so
    the table never grows without bound under sustained traffic."""
    expired = [k for k, (_, exp) in _downgrade_table.items() if now > exp]
    for k in expired:
        _downgrade_table.pop(k, None)


def apply_autorank(
    state,  # AuthorityState — left untyped here to avoid a circular import.
    band: Band,
    band_cfg: BandConfig,
    request,
) -> Band:
    """Return the effective band for `request` given the agent's history.

    Order of operations:
        1. If the band has no `band_after_task` directive, return `band`
           unchanged. The check never even reads the table.
        2. Look up agent_id in the table. If a fresh entry exists
           and points to a different band, return that band.
        3. Otherwise return `band` unchanged.
    """
    if band_cfg.band_after_task is None:
        return band

    # agent_id lives on the request (per the design spec). The SpendRequest
    # dataclass doesn't have an explicit agent_id field today, but the
    # spec for Feature 4 already implies the request carries
    # `requester_agent_id` and `recipient_agent_id`. Reusing that key
    # keeps all the new directives talking the same vocabulary.
    agent_id = getattr(request, "requester_agent_id", None) or getattr(request, "agent_id", None)
    if not agent_id:
        return band

    now = time.time()
    _purge_expired(now)
    entry = _downgrade_table.get(agent_id)
    if entry is None:
        return band
    return entry[0]


def record_successful_request(
    state,
    band: Band,
    band_cfg: BandConfig,
    request,
    *,
    now: Optional[float] = None,
) -> Optional[Band]:
    """Mark a successful (VERIFIED) request as a downgrade trigger.

    Returns the band that was stored (so tests can assert the right
    thing landed in the table), or None if the band has no
    band_after_task directive (no-op).
    """
    if band_cfg.band_after_task is None:
        return None
    agent_id = getattr(request, "requester_agent_id", None) or getattr(request, "agent_id", None)
    if not agent_id:
        return None
    ts = now if now is not None else time.time()
    _downgrade_table[agent_id] = (band_cfg.band_after_task, ts + DOWNGRADE_TTL_SECONDS)
    return band_cfg.band_after_task


def clear_downgrade_table() -> None:
    """Test helper: wipe the in-memory table between tests so they
    don't bleed state. The function is intentionally module-public
    so conftest.py or a fixture can call it."""
    _downgrade_table.clear()
