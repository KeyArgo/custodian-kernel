"""CLI subcommand: `custodian codex-guard receipts`."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _color(verdict: str, is_tty: bool) -> str:
    if not is_tty:
        return verdict
    codes = {"autonomous": "32", "approval_required": "33", "denied": "31"}
    code = codes.get(verdict)
    return f"\x1b[{code}m{verdict}\x1b[0m" if code else verdict


def run(args) -> None:
    from custodian.codex_guard.receipts import ReceiptChain
    state_dir = Path(args.state_dir).resolve()
    chain = ReceiptChain(state_dir)
    path = chain.path

    if not path.exists():
        print("No codex-guard receipts found.")
        return

    records_raw = path.read_text().splitlines()
    records = []
    for i, line in enumerate(records_raw, 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"warning: skipping malformed line {i}", file=sys.stderr)

    if not records:
        print("No codex-guard receipts found.")
        return

    if args.verify:
        try:
            n = chain.verify()
            print(f"chain OK ({n} receipts)")
        except ValueError as e:
            print(f"chain BROKEN at {e}", file=sys.stderr)
            raise SystemExit(2)

    records.sort(key=lambda r: r.get("ts", 0.0))
    limit = args.limit
    if limit <= 0:
        limit = len(records)
    records = records[-limit:]

    is_tty = sys.stdout.isatty()
    for r in records:
        ts = datetime.fromtimestamp(r.get("ts", 0), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        verdict = _color(r.get("verdict", ""), is_tty)
        action = r.get("action_kind", "")
        band = r.get("band", "")
        tool = r.get("tool", "")
        reason = r.get("reason", "")
        if len(reason) > 80:
            reason = reason[:80] + "…"
        mac = r.get("mac", "")
        short_mac = mac[:12]
        print(
            f"{ts}  {verdict:18s}  {action:12s}  {band:4s}  {tool:12s}  {reason:80s}  {short_mac}"
        )

    autonomous = sum(1 for r in records if r.get("verdict") == "autonomous")
    approval_required = sum(
        1 for r in records if r.get("verdict") == "approval_required"
    )
    denied = sum(1 for r in records if r.get("verdict") == "denied")
    print(
        f"Total: {len(records)} receipts "
        f"(autonomous={autonomous}, "
        f"approval_required={approval_required}, "
        f"denied={denied})"
    )
