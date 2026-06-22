from __future__ import annotations

import sys
from pathlib import Path

from custodian.ledger import Ledger
from custodian.storage.sqlite import SqliteStorage
from custodian.types import Band


def _band_str(b: Band | str) -> str:
    return b.value if isinstance(b, Band) else str(b)


def _print_default() -> None:
    print("No authority state initialized. Defaults would be:")
    print("  Band: L2")
    print("  Per-action cap: $2.00")
    print("  Session cap: $10.00")
    print("  Spent this session: $0.00")
    print("  Remaining: $10.00")


def run(args) -> None:
    state_dir = Path(args.state_dir).resolve()
    db_path = state_dir / "custodian.db"

    if not db_path.exists():
        _print_default()
        return

    try:
        storage = SqliteStorage(db_path)
        state = storage.load_authority_state()
        kill_state = storage.get_kill_switch()
    except Exception as e:
        print(f"error: failed to read state: {e}", file=sys.stderr)
        raise SystemExit(1)

    if kill_state.killed:
        print(f"*** KILL SWITCH ENGAGED *** (by {kill_state.by or 'unknown'})")
        if kill_state.reason:
            print(f"    Reason: {kill_state.reason}")
        print()

    if state is None:
        _print_default()
        return

    ledger = Ledger(storage)
    print(f"Band: {_band_str(state.band)}")
    print(f"Per-action cap: ${state.per_action_cap:.2f}")
    print(f"Session cap: ${state.session_cap:.2f}")
    print(f"Spent this session: ${state.spent_this_session:.2f}")
    print(f"Remaining: ${ledger.remaining_budget(state):.2f}")
    print(f"  Autonomous spend:        ${ledger.total_spent(autonomous_only=True):.2f}")
    print(f"  Human-approved override: ${ledger.total_spent(approved_only=True):.2f}")
