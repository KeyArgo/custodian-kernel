"""custodian confirm <request-id> — close-the-loop confirmation for a spend.

The agent calls this within N seconds (default 60) of completing a skill
call. The flow:

  1. Look up `request-id` in the audit ledger. We treat the id as either
     an entry's `payment_intent_id` (the Stripe-side id assigned to a real
     payment) or its numeric row id in the audit log. If neither matches,
     the request is unknown and we exit 1.
  2. If the request is found and its `ts` is within the deadline, the
     confirmation is logged as a fresh "verified" audit entry and the CLI
     prints the success line.
  3. If the request is found but older than the deadline, the CLI prints
     the deadline-missed line and exits with code 1. The original entry is
     not modified.

The fresh "verified" append is what closes the audit loop: every spend
eventually lands in the ledger either as a clean `executed` followed by
`verified`, or it sits there past-deadline and is flagged for review.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from custodian.config import CustodianConfig
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band


def _default_deadline_seconds() -> int:
    """The deadline for a confirmation. 60s is the spec default."""
    return 60


def _find_entry(entries: list, request_id: str) -> tuple[int, AuditEntry] | None:
    """Find an entry whose payment_intent_id or row id matches request_id.

    Returns (index, entry) on match, else None.
    """
    # Try payment_intent_id first (the canonical request id for paid spends).
    for i, e in enumerate(entries):
        if e.payment_intent_id and e.payment_intent_id == request_id:
            return i, e
    # Fall back to numeric row id (sqlite assigns an auto-increment id to
    # every audit_log row). The entries list is in insertion order so the
    # row id is index + 1.
    if request_id.isdigit():
        idx = int(request_id) - 1
        if 0 <= idx < len(entries):
            return idx, entries[idx]
    return None


def _verdict_label(entry: AuditEntry) -> str:
    """Infer the verdict label for an entry's display."""
    return entry.event.upper()


def run(args) -> int:
    request_id = getattr(args, "request_id", None)
    if not request_id:
        print("usage: custodian confirm <request-id>", file=sys.stderr)
        return 1

    deadline = int(getattr(args, "deadline", _default_deadline_seconds()))

    state_dir_raw = getattr(args, "state_dir", None)
    if state_dir_raw:
        state_dir = Path(state_dir_raw).resolve()
    else:
        state_dir = CustodianConfig.from_env().state_dir

    db_path = state_dir / "custodian.db"
    if not db_path.exists():
        # Treat the empty case as "not found" — same UX as a missing entry.
        print(f"request {request_id} not found")
        return 1

    storage = SqliteStorage(db_path)
    entries = storage.read_audit_entries()
    found = _find_entry(entries, request_id)
    if found is None:
        print(f"request {request_id} not found")
        return 1

    _, entry = found
    now = time.time()
    age = now - entry.ts

    if age <= deadline:
        # Mark VERIFIED: append a fresh "verified" audit entry. We don't
        # mutate the original — the audit log is append-only.
        try:
            storage.append_audit_entry(
                AuditEntry(
                    event="verified",
                    amount=entry.amount,
                    description=f"confirm: {request_id}",
                    band=entry.band,
                    payment_intent_id=entry.payment_intent_id,
                )
            )
        except Exception as e:
            print(f"error: failed to record confirmation: {e}", file=sys.stderr)
            return 1
        print(f"✓ request {request_id} confirmed within {deadline}s")
        return 0

    # Past deadline: don't mark VERIFIED. Per spec we mark it UNVERIFIED by
    # appending an audit entry. The original entry is untouched.
    try:
        storage.append_audit_entry(
            AuditEntry(
                event="unverified",
                amount=entry.amount,
                description=f"confirm: {request_id} (past deadline)",
                band=entry.band,
                payment_intent_id=entry.payment_intent_id,
            )
        )
    except Exception as e:
        print(f"error: failed to record unverified status: {e}", file=sys.stderr)
        return 1
    age_int = int(age)
    print(f"✗ request {request_id} past deadline ({age_int} seconds old), marked UNVERIFIED")
    return 1
