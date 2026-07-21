from __future__ import annotations

import sys
import uuid
from pathlib import Path

from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry, Band, KillSwitchState
from custodian.universal_ledger import LedgerEvent, UniversalLedger


def run(args) -> None:
    state_dir = Path(args.state_dir).resolve()
    db_path = state_dir / "custodian.db"

    try:
        storage = SqliteStorage(db_path)
    except Exception as e:
        print(f"error: failed to open state database: {e}", file=sys.stderr)
        raise SystemExit(1)

    current = storage.get_kill_switch()
    if not current.killed:
        print("Kill switch is not engaged -- nothing to resume.")
        return

    storage.set_kill_switch(KillSwitchState(killed=False, reason="", by=args.by))
    try:
        storage.append_audit_entry(AuditEntry(
            event="kill_switch_released", amount=0.0,
            description="kill switch released", band=Band.L0,
            approved_by=args.by,
        ))
    except Exception as e:
        print(f"warning: failed to write audit entry: {e}", file=sys.stderr)
    # See cmd_kill.py: the kill switch's own engage/resume events were
    # invisible to the tamper-evident ledger. Found in review.
    try:
        UniversalLedger(state_dir / "ledger.db").append(LedgerEvent(
            correlation_id=uuid.uuid4().hex, requester=f"cli:resume:{args.by}",
            provider="custodian", action="kill-switch",
            lifecycle_event="approved", band=Band.L0.value, amount=0.0,
            currency="USD", approver=args.by,
        ))
    except Exception as e:
        print(f"warning: failed to write ledger event: {e}", file=sys.stderr)

    print(f"Kill switch released by {args.by}. Normal decisions will resume.")
