from __future__ import annotations

import sys
from pathlib import Path

from custodian.storage.sqlite import SqliteStorage
from custodian.types import Band


def _band_str(b: Band | str) -> str:
    return b.value if isinstance(b, Band) else str(b)


def run(args) -> None:
    state_dir = Path(args.state_dir).resolve()
    db_path = state_dir / "custodian.db"

    if not db_path.exists():
        print("No audit entries found (database does not exist).")
        return

    try:
        storage = SqliteStorage(db_path)
        entries = storage.read_audit_entries()
    except Exception as e:
        print(f"error: failed to read audit log: {e}", file=sys.stderr)
        raise SystemExit(1)

    if args.event:
        entries = [e for e in entries if e.event == args.event]

    if not entries:
        print("No audit entries found.")
        return

    limit = args.limit if args.limit else len(entries)
    for entry in entries[-limit:]:
        d = entry.to_dict()
        ts = d.get("iso", "")
        extra = ""
        if entry.approved_by:
            extra = f" (approved by {entry.approved_by})"
        elif entry.denied_by:
            extra = f" (denied by {entry.denied_by})"
        if entry.payment_intent_id:
            extra += f" id={entry.payment_intent_id}"
        print(f"[{ts}] {d['event']}: ${entry.amount:.2f} '{entry.description}' band={_band_str(entry.band)}{extra}")
