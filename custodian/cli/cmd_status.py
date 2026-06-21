from __future__ import annotations

import sys
from pathlib import Path

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
    except Exception as e:
        print(f"error: failed to read state: {e}", file=sys.stderr)
        raise SystemExit(1)

    if state is None:
        _print_default()
        return

    print(f"Band: {_band_str(state.band)}")
    print(f"Per-action cap: ${state.per_action_cap:.2f}")
    print(f"Session cap: ${state.session_cap:.2f}")
    print(f"Spent this session: ${state.spent_this_session:.2f}")
    print(f"Remaining: ${state.remaining_session_budget():.2f}")
