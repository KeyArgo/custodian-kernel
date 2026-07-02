"""custodian beancount — exports the audit ledger in Beancount v2 format.

Reads the SqliteStorage at --state-dir (default CustodianConfig.from_env())
and writes one transaction per executed/recorded audit entry to stdout.

The spec example shows the format:
    2026-06-29 * "custodian-spend: <skill>"
      Assets:Agent:Test                          0.50 USD
      Expenses:Agent:<skill>

That means each ledger row becomes 3 lines: a header and two postings.
The description field in the ledger carries the skill name (we use the
"custodian-spend: <skill>" form per the example), and the amount becomes
the first posting.

When --since YYYY-MM-DD is passed, only entries on/after that date are
included. With an empty ledger, the output is a valid Beancount header
with no transactions — still parseable.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from custodian.config import CustodianConfig
from custodian.storage.sqlite import SqliteStorage


def _entry_date(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _skill_from_description(description: str) -> str:
    """Extract the skill name from a ledger description.

    The convention in the spec example is "custodian-spend: <skill>".
    If the description doesn't have that prefix, fall back to the raw
    description (truncated) so the export is always well-formed.
    """
    if not description:
        return "unknown"
    # Common forms seen in the codebase:
    #   "custodian-spend: <skill>"
    #   "<skill>"
    #   arbitrary free text
    if ":" in description:
        suffix = description.split(":", 1)[1].strip()
        if suffix:
            return suffix
    return description.strip()[:64] or "unknown"


def _sanitize_account_component(name: str) -> str:
    """Beancount account components disallow certain characters."""
    out = []
    for ch in name:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        else:
            out.append("-")
    s = "".join(out).strip("-")
    return s or "unknown"


def _render_entry(entry) -> str:
    """Render a single AuditEntry as a 3-line Beancount transaction."""
    date = _entry_date(entry.ts)
    skill = _skill_from_description(entry.description)
    skill_account = _sanitize_account_component(skill)
    narration = f"custodian-spend: {skill}"
    amount = f"{entry.amount:.2f} USD"
    return (
        f'{date} * "{narration}"\n'
        f'  Assets:Agent:Test                            {amount}\n'
        f'  Expenses:Agent:{skill_account}\n'
    )


def _parse_since(since: str | None) -> float | None:
    """Parse YYYY-MM-DD into a UTC epoch. None if --since not given."""
    if not since:
        return None
    try:
        dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as e:
        print(f"error: invalid --since date: {since} (expected YYYY-MM-DD)", file=sys.stderr)
        raise SystemExit(1)
    return dt.timestamp()


def run(args) -> int:
    state_dir_raw = getattr(args, "state_dir", None)
    if state_dir_raw:
        state_dir = Path(state_dir_raw).resolve()
    else:
        state_dir = CustodianConfig.from_env().state_dir

    since_epoch = _parse_since(getattr(args, "since", None))

    db_path = state_dir / "custodian.db"
    entries: list = []
    if db_path.exists():
        storage = SqliteStorage(db_path)
        entries = storage.read_audit_entries()

    if since_epoch is not None:
        entries = [e for e in entries if e.ts >= since_epoch]

    # Header: always emitted. Beancount treats lines starting with `;` as
    # comments, so the file is always parseable even when empty.
    iso_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("; Custodian beancount export")
    print(f"; Generated: {iso_now}")
    if not entries:
        print("; No entries.")
        return 0

    # Optional option line for Beancount strict parsers.
    print('option "title_books" "Custodian ledger"')
    for entry in entries:
        sys.stdout.write(_render_entry(entry))
    return 0
