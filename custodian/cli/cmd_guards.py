"""`custodian guards` — enable/disable/status for the harness guards."""
from __future__ import annotations

import argparse

from custodian.guards import gate

_LABELS = {
    "codex": "Codex guard",
    "claude": "Claude Code guard",
    "hermes": "Hermes guard (plugin)",
}


def _state_dir(args: argparse.Namespace) -> str:
    return getattr(args, "state_dir", None) or gate.default_state_dir()


def run_enable(args: argparse.Namespace) -> int:
    changed = gate.enable(_state_dir(args), args.name)
    print(
        f"{_LABELS.get(args.name, args.name)}: enabled"
        if changed
        else f"{_LABELS.get(args.name, args.name)}: already enabled"
    )
    print(f"state: {gate.state_path(_state_dir(args))}")
    return 0


def run_disable(args: argparse.Namespace) -> int:
    changed = gate.disable(_state_dir(args), args.name)
    print(
        f"{_LABELS.get(args.name, args.name)}: disabled"
        if changed
        else f"{_LABELS.get(args.name, args.name)}: already disabled"
    )
    return 0


def run_status(args: argparse.Namespace) -> int:
    report = gate.status_report(_state_dir(args))
    active = 0
    for rec in report:
        mark = "on " if rec["enabled"] else "off"
        print(f"  {mark}  {_LABELS.get(rec['name'], rec['name'])} ({rec['name']})")
        active += 1 if rec["enabled"] else 0
    print(
        f"\n{active} of {len(report)} guards active. "
        "Guards are dormant until enabled; activation never happens implicitly."
    )
    return 0
