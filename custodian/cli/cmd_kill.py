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

    storage.set_kill_switch(KillSwitchState(
        killed=True, reason=args.reason or "", by=args.by,
    ))
    try:
        storage.append_audit_entry(AuditEntry(
            event="kill_switch_engaged", amount=0.0,
            description=args.reason or "kill switch engaged", band=Band.L0,
            denied_by=args.by,
        ))
    except Exception as e:
        print(f"warning: failed to write audit entry: {e}", file=sys.stderr)
    # The kill switch's own engage/resume events used to be invisible to the
    # tamper-evident ledger entirely -- the highest-consequence, most
    # security-relevant events this kernel has (everything stops, or starts
    # again) had no hash-chained record, unlike an ordinary spend request.
    # Found in review.
    try:
        UniversalLedger(state_dir / "ledger.db").append(LedgerEvent(
            correlation_id=uuid.uuid4().hex, requester=f"cli:kill:{args.by}",
            provider="custodian", action="kill-switch",
            lifecycle_event="denied", band=Band.L0.value, amount=0.0,
            currency="USD", metadata={"reason": (args.reason or "")[:200]},
        ))
    except Exception as e:
        print(f"warning: failed to write ledger event: {e}", file=sys.stderr)

    print(f"KILL SWITCH ENGAGED by {args.by}. Every request will be denied until "
          f"'custodian resume' is run.")
    if args.reason:
        print(f"Reason: {args.reason}")
