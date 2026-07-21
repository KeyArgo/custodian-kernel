"""Human-facing control plane for Custodian Codex Guard."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .approvals import ApprovalError, ApprovalStore
from .mcp_server import _state_dir
from .receipts import ReceiptChain

PLUGIN_ID = "custodian-codex-guard@custodian-build-week"


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None or (Path(sys.executable).parent / name).exists()


def _repo_root() -> Path | None:
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (candidate / ".agents" / "plugins" / "marketplace.json").is_file():
            return candidate
    return None


def cmd_setup(args: argparse.Namespace) -> int:
    root = _repo_root()
    if root is None:
        print("plugin marketplace not found; run setup from the Custodian checkout", file=sys.stderr)
        return 1
    commands = [
        ["codex", "plugin", "marketplace", "add", str(root)],
        ["codex", "plugin", "add", PLUGIN_ID],
    ]
    if args.dry_run:
        for command in commands:
            print("would run: " + " ".join(command))
        return 0
    if not _command_available("codex"):
        print("Codex CLI is not installed or not on PATH", file=sys.stderr)
        return 1
    if not _command_available("custodian-codex-guard-mcp"):
        print(
            "Guard MCP command is missing; install this package first with "
            "'python -m pip install .'",
            file=sys.stderr,
        )
        return 1
    for command in commands:
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"setup failed: {type(exc).__name__}", file=sys.stderr)
            return 1
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            print(f"setup failed: {detail}", file=sys.stderr)
            return 1
    print(f"installed and enabled: {PLUGIN_ID}")
    print("start a new Codex thread to load the guard")
    return 0


def cmd_disable(_: argparse.Namespace) -> int:
    """Operator escape hatch: remove the plugin without deleting evidence."""
    if not _command_available("codex"):
        print("Codex CLI is not installed or not on PATH", file=sys.stderr)
        return 1
    try:
        result = subprocess.run(
            ["codex", "plugin", "remove", PLUGIN_ID],
            text=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"disable failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if result.returncode:
        print(f"disable failed: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
        return 1
    print("Codex Guard disabled; receipts and approval evidence were preserved.")
    print("start a new Codex thread to apply the change")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    operator = args.operator or os.environ.get("USER") or os.environ.get("USERNAME")
    if not operator:
        print("operator identity is required (--operator NAME)", file=sys.stderr)
        return 2
    store = ApprovalStore(_state_dir())
    approval_id = args.approval_id
    if approval_id == "latest":
        pending = []
        paths = store.approvals_dir.glob("*.json") if store.approvals_dir.exists() else ()
        for path in paths:
            try:
                candidate = store.get(path.stem)
            except (OSError, ApprovalError):
                continue
            if candidate.status == "pending" and candidate.expires_at >= time.time():
                pending.append(candidate)
        if not pending:
            print("approval denied: no unexpired pending approvals", file=sys.stderr)
            return 1
        approval_id = max(pending, key=lambda item: item.created_at).approval_id
    try:
        pending_record = store.get(approval_id)
        remaining = max(0, int(pending_record.expires_at - time.time()))
        digest = args.digest or pending_record.action_digest
        print(f"Approval: {approval_id}")
        print(f"Requester: {pending_record.requester}")
        print(f"Action digest: {pending_record.action_digest}")
        print(f"Expires in: {remaining // 60}m {remaining % 60:02d}s")
        if not sys.stdin.isatty():
            print(
                "approval denied: run this command in an interactive operator terminal",
                file=sys.stderr,
            )
            return 1
        answer = input("Approve this exact action once? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("approval cancelled")
            return 1
        record = store.approve(
            approval_id,
            approved_by=operator,
            expected_digest=digest,
        )
    except ApprovalError as exc:
        print(f"approval denied: {exc}", file=sys.stderr)
        return 1
    print(f"approved once: {record.approval_id} (expires {record.expires_at:.0f})")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    state = _state_dir()
    store = ApprovalStore(state)
    approval_dir = store.approvals_dir
    counts: dict[str, int] = {}
    for path in approval_dir.glob("*.json") if approval_dir.exists() else ():
        try:
            status = store.get(path.stem).status
        except (OSError, ApprovalError):
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
        "codex CLI": _command_available("codex"),
        "MCP command": _command_available("custodian-codex-guard-mcp"),
    }
    for name, passed in checks.items():
        print(f"{'OK' if passed else 'MISSING'}  {name}")
    print("NOTE  Consequential actions fail closed unless an exact approval is consumed.")
    return 0 if all(checks.values()) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="custodian-codex")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="install and enable the Codex plugin")
    setup.add_argument("--dry-run", action="store_true")
    setup.set_defaults(fn=cmd_setup)
    disable = sub.add_parser("disable", help="operator escape hatch; preserve evidence")
    disable.set_defaults(fn=cmd_disable)
    approve = sub.add_parser("approve", help="approve one exact pending action")
    approve.add_argument("approval_id", help="approval UUID, or 'latest'")
    approve.add_argument(
        "--digest",
        help="optional full digest copied from Guard for independent verification",
    )
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
