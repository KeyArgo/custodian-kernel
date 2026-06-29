from __future__ import annotations

import argparse
import sys

from custodian.cli import (
    cmd_init, cmd_validate, cmd_status, cmd_audit, cmd_request, cmd_approve,
    cmd_deny, cmd_kill, cmd_resume,
)
from custodian.cli import cmd_tools, cmd_demo_verify
from custodian.config import CustodianConfig


def main(argv: list[str] | None = None) -> int:
    # Defaults come from CustodianConfig.from_env() (CUSTODIAN_STATE_DIR,
    # CUSTODIAN_POLICY_PATH env vars), so the same workspace works
    # un-flagged in Docker/CI where passing flags every invocation is
    # awkward -- explicit --state-dir/--policy flags still override.
    env_defaults = CustodianConfig.from_env()

    parser = argparse.ArgumentParser(prog="custodian", description="Authority and spend governance CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Scaffold a new custodian workspace")
    p.add_argument("--dir", default=".", help="Target directory (default: .)")
    p.set_defaults(func=cmd_init.run)

    p = sub.add_parser("validate", help="Validate a policy file")
    p.add_argument("policy_path", help="Path to policy YAML file")
    p.set_defaults(func=cmd_validate.run)

    p = sub.add_parser("status", help="Show current authority state")
    p.add_argument("--state-dir", default=str(env_defaults.state_dir), help="State directory")
    p.set_defaults(func=cmd_status.run)

    p = sub.add_parser("audit", help="Show audit log entries")
    p.add_argument("--state-dir", default=str(env_defaults.state_dir), help="State directory")
    p.add_argument("--limit", type=int, default=50, help="Max entries to show (default: 50)")
    p.add_argument("--event", help="Filter by event type")
    p.set_defaults(func=cmd_audit.run)

    p = sub.add_parser("request", help="Request a spend decision")
    p.add_argument("--amount", type=float, required=True, help="Amount to request")
    p.add_argument("--description", required=True, help="Description of the spend")
    p.add_argument("--skill", help="Optional skill name for policy matching")
    p.add_argument(
        "--context", action="append", default=[], metavar="FLAG=true|false",
        help="Context flag for rule matching (repeatable, e.g. --context critical=true)",
    )
    p.add_argument("--state-dir", default=str(env_defaults.state_dir), help="State directory")
    p.add_argument("--policy", default=str(env_defaults.policy_path), help="Policy file")
    p.set_defaults(func=cmd_request.run)

    p = sub.add_parser("approve", help="Approve a pending escalation")
    p.add_argument("code", help="Verification code from operator's phone")
    p.add_argument("--approved-by", required=True, help="Name/ID of the approving human")
    p.add_argument("--state-dir", default=str(env_defaults.state_dir), help="State directory")
    p.set_defaults(func=cmd_approve.run)

    p = sub.add_parser("deny", help="Deny a pending escalation")
    p.add_argument("--denied-by", required=True, help="Name/ID of the denying human")
    p.add_argument("--state-dir", default=str(env_defaults.state_dir), help="State directory")
    p.set_defaults(func=cmd_deny.run)

    p = sub.add_parser("kill", help="Engage the kill switch -- deny every request until released")
    p.add_argument("--by", required=True, help="Name/ID of the operator engaging it")
    p.add_argument("--reason", default="", help="Why the kill switch is being engaged")
    p.add_argument("--state-dir", default=str(env_defaults.state_dir), help="State directory")
    p.set_defaults(func=cmd_kill.run)

    p = sub.add_parser("resume", help="Release the kill switch")
    p.add_argument("--by", required=True, help="Name/ID of the operator releasing it")
    p.add_argument("--state-dir", default=str(env_defaults.state_dir), help="State directory")
    p.set_defaults(func=cmd_resume.run)

    p = sub.add_parser("demo-verify", help="Run 4 hardcoded claim-verification scenarios (no credentials needed)")
    p.set_defaults(func=cmd_demo_verify.run)

    # tools subcommand
    tools_parser = sub.add_parser("tools", help="List and invoke Custodian-governed tools")
    tools_sub = tools_parser.add_subparsers(dest="tools_command", required=True)

    ts = tools_sub.add_parser("list", help="List all registered tools with authority bands")
    ts.set_defaults(func=cmd_tools.cmd_tools_list)

    ts = tools_sub.add_parser("run", help="Invoke a governed tool by name")
    ts.add_argument("tool", help="Tool name (see: custodian tools list)")
    ts.add_argument("kwargs", nargs=argparse.REMAINDER, help="--key value pairs passed to the tool")
    ts.set_defaults(func=cmd_tools.cmd_tools_run)

    ts = tools_sub.add_parser("summary", help="Print tool count and band breakdown as JSON")
    ts.set_defaults(func=cmd_tools.cmd_tools_summary)

    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
