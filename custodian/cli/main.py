from __future__ import annotations

import argparse
import sys

from custodian.cli import cmd_init, cmd_validate, cmd_status, cmd_audit, cmd_request, cmd_approve, cmd_deny


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="custodian", description="Authority and spend governance CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Scaffold a new custodian workspace")
    p.add_argument("--dir", default=".", help="Target directory (default: .)")
    p.set_defaults(func=cmd_init.run)

    p = sub.add_parser("validate", help="Validate a policy file")
    p.add_argument("policy_path", help="Path to policy YAML file")
    p.set_defaults(func=cmd_validate.run)

    p = sub.add_parser("status", help="Show current authority state")
    p.add_argument("--state-dir", default="./state", help="State directory (default: ./state)")
    p.set_defaults(func=cmd_status.run)

    p = sub.add_parser("audit", help="Show audit log entries")
    p.add_argument("--state-dir", default="./state", help="State directory (default: ./state)")
    p.add_argument("--limit", type=int, default=50, help="Max entries to show (default: 50)")
    p.add_argument("--event", help="Filter by event type")
    p.set_defaults(func=cmd_audit.run)

    p = sub.add_parser("request", help="Request a spend decision")
    p.add_argument("--amount", type=float, required=True, help="Amount to request")
    p.add_argument("--description", required=True, help="Description of the spend")
    p.add_argument("--skill", help="Optional skill name for policy matching")
    p.add_argument("--state-dir", default="./state", help="State directory (default: ./state)")
    p.add_argument("--policy", default="./policy.yaml", help="Policy file (default: ./policy.yaml)")
    p.set_defaults(func=cmd_request.run)

    p = sub.add_parser("approve", help="Approve a pending escalation")
    p.add_argument("code", help="Verification code from operator's phone")
    p.add_argument("--approved-by", required=True, help="Name/ID of the approving human")
    p.add_argument("--state-dir", default="./state", help="State directory (default: ./state)")
    p.set_defaults(func=cmd_approve.run)

    p = sub.add_parser("deny", help="Deny a pending escalation")
    p.add_argument("--denied-by", required=True, help="Name/ID of the denying human")
    p.add_argument("--state-dir", default="./state", help="State directory (default: ./state)")
    p.set_defaults(func=cmd_deny.run)

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
