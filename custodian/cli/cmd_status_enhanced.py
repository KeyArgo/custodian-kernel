"""custodian status-banner — a one-screen dashboard of the ledger.

Prints today's date (UTC), the total spend-request count, a verdict
breakdown, the last five audit entries, and the current kill-switch state.
Default state directory comes from CustodianConfig.from_env(); callers can
override with --state-dir. If the ledger is empty, prints a short hint and
exits cleanly.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from custodian.config import CustodianConfig
from custodian.storage.sqlite import SqliteStorage


# Map raw audit-log event names to the four "verdict" buckets the banner
# surfaces. Anything not in this table is reported as UNVERIFIED so the
# banner is forward-compatible with new event types. The keys are the events
# the CLI actually emits: executed/escalated/denied (cmd_request), approved
# (cmd_approve), verified/unverified (cmd_confirm), and the kill-switch pair
# (cmd_kill/cmd_resume).
_VERDICT_FOR_EVENT = {
    "executed": "VERIFIED",
    "approved": "VERIFIED",
    "verified": "VERIFIED",
    "denied": "CONTRADICTED",
    "escalated": "ESCALATED",
    "unverified": "UNVERIFIED",
    "kill_switch_engaged": "UNVERIFIED",
    "kill_switch_released": "UNVERIFIED",
}


def _verdict_for(entry) -> str:
    return _VERDICT_FOR_EVENT.get(entry.event, "UNVERIFIED")


def _format_ts(ts: float) -> str:
    if not ts:
        return "                  "
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))


def _format_kill_state(killed: bool) -> str:
    return "ENGAGED" if killed else "RELEASED"


def _print_empty_banner() -> None:
    print("CUSTODIAN | ledger empty | no spend requests yet")
    print("Run `custodian demo verify` to see the claim verifier in action.")


def _print_banner(
    today_utc: str,
    total: int,
    verdict_counts: dict[str, int],
    last_entries: list,
    kill_label: str,
) -> None:
    """Render the banner. Kept to <= 24 lines on a single screen."""
    print("=" * 60)
    print(f"  CUSTODIAN STATUS BANNER   (UTC {today_utc})")
    print("=" * 60)
    print(f"  Total spend requests: {total}")
    print(
        f"  Verdicts: VERIFIED={verdict_counts.get('VERIFIED', 0)}  "
        f"CONTRADICTED={verdict_counts.get('CONTRADICTED', 0)}  "
        f"ESCALATED={verdict_counts.get('ESCALATED', 0)}  "
        f"UNVERIFIED={verdict_counts.get('UNVERIFIED', 0)}"
    )
    print(f"  Kill switch: {kill_label}")
    print("-" * 60)
    if not last_entries:
        print("  (no recent audit entries)")
    else:
        print("  Last 5 audit entries:")
        print("  timestamp (UTC)      action       amount   band  verdict")
        for e in last_entries:
            ts = _format_ts(e.ts)
            print(
                f"  {ts}  {e.event:<11}  ${e.amount:>6.2f}  {str(e.band):<5} "
                f"{_verdict_for(e)}"
            )
    print("=" * 60)


def run(args) -> int:
    # Resolve the state directory. Precedence: --state-dir flag, then
    # CUSTODIAN_STATE_DIR env var (via CustodianConfig), then ./state.
    state_dir_raw = getattr(args, "state_dir", None)
    if state_dir_raw:
        state_dir = Path(state_dir_raw).resolve()
    else:
        state_dir = CustodianConfig.from_env().state_dir

    db_path = state_dir / "custodian.db"

    if not db_path.exists():
        # The spec says: when the ledger is empty, print this exact block.
        _print_empty_banner()
        return 0

    storage = SqliteStorage(db_path)
    entries = storage.read_audit_entries()

    if not entries:
        _print_empty_banner()
        return 0

    # Count verdicts across the full ledger.
    verdict_counts: dict[str, int] = {
        "VERIFIED": 0,
        "CONTRADICTED": 0,
        "ESCALATED": 0,
        "UNVERIFIED": 0,
    }
    for e in entries:
        verdict_counts[_verdict_for(e)] += 1

    # Last 5 entries (most recent first); the spec's wording "last 5 audit
    # entries" matches the tail of the log.
    last_entries = entries[-5:]

    # Kill-switch state. If the field is absent from storage, treat as
    # RELEASED -- which is the same default SqliteStorage.get_kill_switch()
    # returns.
    kill_state = storage.get_kill_switch()
    kill_label = _format_kill_state(kill_state.killed)

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _print_banner(today_utc, len(entries), verdict_counts, last_entries, kill_label)
    return 0
