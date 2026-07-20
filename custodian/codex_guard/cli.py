"""Human-facing control plane for Custodian Codex Guard."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

from .approvals import ApprovalError, ApprovalStore
from .mcp_server import _state_dir
from .receipts import ReceiptChain


def _record(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_approve(args: argparse.Namespace) -> int:
    operator = args.operator or os.environ.get("USER") or os.environ.get("USERNAME")
    if not operator:
        print("operator identity is required (--operator NAME)", file=sys.stderr)
        return 2
    try:
        record = ApprovalStore(_state_dir()).approve(args.approval_id, approved_by=operator)
    except ApprovalError as exc:
        print(f"approval denied: {exc}", file=sys.stderr)
        return 1
    print(f"approved once: {record.approval_id} (expires {record.expires_at:.0f})")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    state = _state_dir()
    approval_dir = state / "codex-approvals"
    counts: dict[str, int] = {}
    for path in approval_dir.glob("*.json") if approval_dir.exists() else ():
        try:
            status = str(_record(path).get("status", "invalid"))
        except (OSError, json.JSONDecodeError):
            status = "invalid"
        counts[status] = counts.get(status, 0) + 1
    print(f"state: {state}")
    print("approvals: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"))
    try:
        print(f"receipts: valid ({ReceiptChain(state).verify()})")
        return 0
    except Exception as exc:
        print(f"receipts: INVALID ({exc})")
        return 1


def cmd_doctor(_: argparse.Namespace) -> int:
    checks = {
        "python": sys.version_info >= (3, 11),
        "codex CLI": shutil.which("codex") is not None,
        "MCP command": shutil.which("custodian-codex-guard-mcp") is not None,
    }
    for name, passed in checks.items():
        print(f"{'OK' if passed else 'MISSING'}  {name}")
    print("NOTE  Consequential actions fail closed unless an exact approval is consumed.")
    return 0 if all(checks.values()) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="custodian-codex")
    sub = parser.add_subparsers(dest="command", required=True)
    approve = sub.add_parser("approve", help="approve one exact pending action")
    approve.add_argument("approval_id")
    approve.add_argument("--operator")
    approve.set_defaults(fn=cmd_approve)
    status = sub.add_parser("status", help="verify receipts and show approval counts")
    status.set_defaults(fn=cmd_status)
    doctor = sub.add_parser("doctor", help="check the local Codex Guard installation")
    doctor.set_defaults(fn=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
