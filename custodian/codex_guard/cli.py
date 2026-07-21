"""Human-facing control plane for Custodian Codex Guard."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import shutil

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


def _mcp_command() -> list[str]:
    """Return the canonical command for launching the MCP guard server.

    Uses ``sys.executable -m custodian.codex_guard.mcp_server`` so the
    registration always points at the running interpreter rather than a
    possibly-stale bare shell script.
    """
    return [sys.executable, "-m", "custodian.codex_guard.mcp_server"]


def _verify_mcp_handshake(command: list[str]) -> bool:
    """Verify the MCP server responds to a JSON-RPC ``initialize`` call."""
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "custodian-test", "version": "0.0.0"},
        },
    })
    try:
        proc = subprocess.run(
            command,
            input=request + "\n",
            text=True,
            capture_output=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return False
        for line in proc.stdout.strip().splitlines():
            if not line.strip():
                continue
            resp = json.loads(line)
            if resp.get("result") and resp.get("id") == 1:
                return True
        return False
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return False


def _ensure_mcp_json(mcp_json_path: Path) -> bool:
    """Idempotently write/repair the MCP server registration.

    Always uses the absolute ``sys.executable -m custodian.codex_guard.mcp_server``
    form so stale bare-command registrations are replaced on every run.
    Verifies with a real JSON-RPC ``initialize`` handshake.
    """
    command = _mcp_command()

    payload: dict = {}

    if mcp_json_path.exists():
        try:
            existing = json.loads(mcp_json_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = existing
            if (
                existing.get("mcpServers", {}).get("custodian-codex-guard", {}).get("command")
                != command[0]
                or existing.get("mcpServers", {}).get("custodian-codex-guard", {}).get("args")
                != command[1:]
            ):
                print(f"replacing stale MCP registration at {mcp_json_path}")
        except (json.JSONDecodeError, OSError):
            pass  # corrupt file → overwrite

    servers = payload.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        payload["mcpServers"] = servers
    servers["custodian-codex-guard"] = {
        "command": command[0],
        "args": command[1:],
    }

    mcp_json_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_json_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    # Verify with an actual JSON-RPC handshake
    if _verify_mcp_handshake(command):
        print(f"MCP server at {mcp_json_path} verified via JSON-RPC initialize handshake")
        return True
    else:
        print(
            f"MCP server handshake failed — command: {' '.join(command)}",
            file=sys.stderr,
        )
        return False


def cmd_setup(args: argparse.Namespace) -> int:
    root = _repo_root()
    if root is None:
        print("plugin marketplace not found; run setup from the Custodian checkout", file=sys.stderr)
        return 1

    commands = [
        ["codex", "plugin", "marketplace", "add", str(root)],
        ["codex", "plugin", "add", PLUGIN_ID],
        ["codex", "mcp", "add", "custodian-codex-guard", "--", *_mcp_command()],
    ]
    if args.dry_run:
        print("would run: " + " ".join(_mcp_command()))
        for command in commands:
            print("would run: " + " ".join(command))
        return 0

    plugin_mcp = root / "plugins" / "custodian-codex-guard" / ".mcp.json"
    if not _ensure_mcp_json(plugin_mcp):
        print("MCP server registration failed — guard is not reachable", file=sys.stderr)
        return 1
    if not _command_available("codex"):
        print("Codex CLI is not installed or not on PATH", file=sys.stderr)
        return 1
    # Remove a stale global registration before installing the exact absolute
    # interpreter command. A missing registration is expected on first setup.
    subprocess.run(
        ["codex", "mcp", "remove", "custodian-codex-guard"],
        text=True, capture_output=True, timeout=30,
    )
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


def _diagnose_stale_registration(mcp_json_path: Path) -> tuple[bool, str]:
    """Compare the registered MCP command/args against the live interpreter.

    Returns (is_stale, detail_string).  Stale means the command or args
    diverge from what ``sys.executable -m`` would produce, which happens
    when the Python interpreter was upgraded or the installation moved.
    """
    if not mcp_json_path.exists():
        return False, "no mcp.json found at " + str(mcp_json_path)

    try:
        registered = json.loads(mcp_json_path.read_text(encoding="utf-8"))
        cmd_entry = (
            registered.get("mcpServers", {})
            .get("custodian-codex-guard", {})
            .get("command", "")
        )
        args_entry = registered.get("mcpServers", {}).get(
            "custodian-codex-guard", {}
        ).get("args", [])
    except (json.JSONDecodeError, OSError):
        return False, "mcp.json parse error"

    current_cmd = sys.executable
    current_args = ["-m", "custodian.codex_guard.mcp_server"]

    detail = f"registered: {cmd_entry} {' '.join(args_entry)}  live: {current_cmd} {' '.join(current_args)}"

    if cmd_entry != current_cmd or args_entry != current_args:
        return True, detail

    return False, detail


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose the Custodian Codex Guard installation and the registered interpreter."""
    results: list[tuple[str, bool, str]] = []

    # Python version
    ok = sys.version_info >= (3, 11)
    results.append(("python", ok, f"{sys.version.split()[0]}"))

    # Codex CLI
    has_codex = _command_available("codex")
    results.append(("codex CLI", has_codex, shutil.which("codex") or "not on PATH"))

    # MCP command (canonical form)
    mcp_cmd = _mcp_command()
    mcp_available = _verify_mcp_handshake(mcp_cmd)
    results.append(
        ("MCP server", mcp_available, " ".join(mcp_cmd)),
    )

    # cwd mcp.json interpreter freshness
    mcp_json_path = Path.cwd() / "mcp.json"
    if mcp_json_path.exists():
        try:
            registered = json.loads(mcp_json_path.read_text(encoding="utf-8"))
            cmd_entry = (
                registered.get("mcpServers", {})
                .get("custodian-codex-guard", {})
                .get("command", "")
            )
            args_entry = registered.get("mcpServers", {}).get(
                "custodian-codex-guard", {}
            ).get("args", [])
            detail = f"{cmd_entry} {' '.join(args_entry)}"
            results.append(
                ("registered interpreter", bool(cmd_entry), detail),
            )

            # Diagnose stale registration: compare against current interpreter.
            is_stale, stale_detail = _diagnose_stale_registration(mcp_json_path)
            tag = "stale" if is_stale else "in sync"
            results.append(("cwd freshness", True, f"{tag}: {stale_detail}"))

            # Validate actual JSON-RPC initialize against the *registered* command.
            if cmd_entry:
                reg_cmd = [cmd_entry] + args_entry
                reg_handshake = _verify_mcp_handshake(reg_cmd)
                results.append(
                    ("cwd handshake", reg_handshake, "registered command OK" if reg_handshake else "registered command FAIL"),
                )

        except (json.JSONDecodeError, OSError):
            results.append(("mcp.json", False, "parse error"))

    # Plugin .mcp.json interpreter freshness
    root = _repo_root()
    if root is not None:
        plugin_mcp = root / "plugins" / "custodian-codex-guard" / ".mcp.json"
        if plugin_mcp.exists():
            is_stale, stale_detail = _diagnose_stale_registration(plugin_mcp)
            tag = "stale" if is_stale else "in sync"
            results.append(
                ("plugin .mcp.json", not is_stale, f"{tag}: {stale_detail}"),
            )
            if not is_stale:
                try:
                    reg = json.loads(plugin_mcp.read_text(encoding="utf-8"))
                    cmd_entry = reg.get("mcpServers", {}).get("custodian-codex-guard", {}).get("command", "")
                    args_entry = reg.get("mcpServers", {}).get("custodian-codex-guard", {}).get("args", [])
                    if cmd_entry:
                        reg_handshake = _verify_mcp_handshake([cmd_entry] + args_entry)
                        results.append(
                            ("plugin handshake", reg_handshake, "OK" if reg_handshake else "FAIL"),
                        )
                except (json.JSONDecodeError, OSError):
                    results.append(("plugin .mcp.json", False, "parse error"))

    # Approval store
    state = _state_dir()
    try:
        store = ApprovalStore(state)
        _ = store.list_records()
        results.append(("approval store", True, str(store.approvals_dir)))
    except Exception as exc:
        results.append(("approval store", False, str(exc)))

    # Receipt chain
    try:
        chain = ReceiptChain(state)
        chain.verify()
        results.append(("receipt chain", True, "verified"))
    except Exception as exc:
        results.append(("receipt chain", False, str(exc)))

    for name, passed, detail in results:
        tag = "OK" if passed else "FAIL"
        print(f"  {tag}  {name:<20} {detail}")

    all_ok = all(ok for _, ok, _ in results)
    if all_ok:
        print("\nAll checks passed. Consequential actions fail closed unless approved.")
    else:
        print("\nSome checks failed — see above.", file=sys.stderr)
    return 0 if all_ok else 1


def cmd_deny(args: argparse.Namespace) -> int:
    """Headless denial: reject a pending approval by ID (no TTY required)."""
    store = ApprovalStore(_state_dir())
    operator = args.operator or os.environ.get("USER") or os.environ.get("USERNAME")
    if not operator:
        print("operator identity is required (--operator NAME)", file=sys.stderr)
        return 2

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
            print("deny denied: no unexpired pending approvals", file=sys.stderr)
            return 1
        approval_id = max(pending, key=lambda item: item.created_at).approval_id

    try:
        record = store.get(approval_id)
        if record.status != "pending":
            print(f"deny skipped: approval {approval_id} is {record.status}", file=sys.stderr)
            return 1
        denied = store.deny(approval_id, denied_by=operator)
        print(f"denied: {denied.approval_id} (by {denied.approved_by})")
        return 0
    except ApprovalError as exc:
        print(f"deny failed: {exc}", file=sys.stderr)
        return 1


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
    deny = sub.add_parser("deny", help="headless denial of a pending approval")
    deny.add_argument("approval_id", help="approval UUID, or 'latest'")
    deny.add_argument("--operator", help="operator identity (falls back to $USER)")
    deny.set_defaults(fn=cmd_deny)
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
