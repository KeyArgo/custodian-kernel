from __future__ import annotations

import sys
from pathlib import Path

from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band
from custodian.universal_ledger import LedgerEvent, UniversalLedger


def run(args) -> None:
    state_dir = Path(args.state_dir).resolve()
    db_path = state_dir / "custodian.db"

    try:
        storage = SqliteStorage(db_path)
    except Exception as e:
        print(f"error: failed to open state database: {e}", file=sys.stderr)
        raise SystemExit(1)

    pending = storage.get_pending_approval()
    if pending is None:
        print("error: no pending approval found", file=sys.stderr)
        raise SystemExit(1)

    amount = pending.amount
    description = pending.description
    reason = pending.reason
    correlation_id = pending.correlation_id

    storage.clear_pending_approval()

    entry = AuditEntry(
        event="denied",
        amount=amount,
        description=description,
        band=Band.L2,
        denied_by=args.denied_by,
        reason=reason,
    )
    try:
        storage.append_audit_entry(entry)
    except Exception as e:
        print(f"warning: failed to write audit entry: {e}", file=sys.stderr)

    try:
        UniversalLedger(state_dir / "ledger.db").append(LedgerEvent(
            correlation_id=correlation_id, requester="cli:deny",
            provider="custodian", action="cli-request", lifecycle_event="denied",
            verdict="escalation_required", band=Band.L2.value,
            approver=args.denied_by, amount=amount, currency="USD",
        ))
    except Exception as e:
        print(f"warning: failed to write ledger event: {e}", file=sys.stderr)

    print(f"Denied: ${amount:.2f} for '{description}' by {args.denied_by}")
