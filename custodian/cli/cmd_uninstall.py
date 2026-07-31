"""Data-preserving package uninstall workflow."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _data_locations() -> tuple[Path, ...]:
    return (
        Path.home() / ".custodian",
        Path.home() / ".paladin",
        Path.home() / ".talaria",
    )


def run(args) -> int:
    command = [sys.executable, "-m", "pip", "uninstall", "-y", "custodian-kernel"]
    print("Custodian package uninstall")
    print("===========================")
    print("User data will be preserved:")
    for path in _data_locations():
        print(f"  {path}")
    print("Vaults, policies, ledgers, receipts, and approvals are not deleted.")
    print("\nCommand:")
    print("  " + " ".join(command))
    if args.dry_run:
        print("\nDry run only; nothing was uninstalled.")
        return 0
    if not args.yes:
        print("\nRe-run with --yes to uninstall the package.")
        return 2
    result = subprocess.run(command)
    if result.returncode:
        print(f"Package uninstall failed (exit {result.returncode}).", file=sys.stderr)
        return result.returncode
    print("Package removed. User data was preserved.")
    return 0


def register(sub) -> None:
    parser = sub.add_parser(
        "uninstall",
        help="Remove the kernel package while preserving all user data",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be removed without changing the system")
    parser.add_argument("--yes", action="store_true", help="Confirm package removal")
    parser.set_defaults(func=run)
