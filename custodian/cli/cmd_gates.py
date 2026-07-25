"""Simple personal gate controls shared by all installed adapters."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from custodian.control.settings import ControlSettings, ControlSettingsStore


def _store(state_dir: str) -> ControlSettingsStore:
    return ControlSettingsStore(Path(state_dir) / "control-settings.json")


def describe(settings: ControlSettings) -> str:
    risk = (
        "all matching policy gates may pass automatically, including high-risk actions"
        if settings.enforcement == "open"
        else "credential, destructive, production, money, and governance actions require approval"
    )
    notices = (
        "routine pass-through notices shown"
        if settings.visibility == "verbose"
        else "routine pass-through notices hidden; receipts still recorded"
    )
    return (
        f"Enforcement: {settings.enforcement}\n"
        f"  {risk}\n"
        f"Visibility: {settings.visibility}\n"
        f"  {notices}"
    )


def run(args) -> int:
    store = _store(args.state_dir)
    current = store.load()
    if args.gate_command == "status":
        print(describe(current))
        return 0
    if args.gate_command == "open":
        store.save(replace(current, enforcement="open"))
        print("Open mode enabled for this user.")
        print("WARNING: high-risk actions can now pass automatically when an auto rule matches.")
    elif args.gate_command == "protect":
        store.save(replace(current, enforcement="protected"))
        print("Protected mode enabled for this user.")
    elif args.gate_command == "notifications":
        store.save(replace(current, visibility=args.mode))
        print(f"Routine gate notifications: {args.mode}. Receipts remain enabled.")
    print(describe(store.load()))
    return 0


def register(sub, default_state_dir: str) -> None:
    parser = sub.add_parser("gates", help="View or change personal gate behavior")
    commands = parser.add_subparsers(dest="gate_command", required=True)
    for name, help_text in (
        ("status", "Show enforcement and notification settings"),
        ("open", "Allow matching policy rules to auto-pass every action class"),
        ("protect", "Require approval for high-risk action classes"),
    ):
        item = commands.add_parser(name, help=help_text)
        item.add_argument("--state-dir", default=default_state_dir)
        item.set_defaults(func=run)
    item = commands.add_parser(
        "notifications", help="Show or hide routine auto-approval notices"
    )
    item.add_argument("mode", choices=["verbose", "quiet"])
    item.add_argument("--state-dir", default=default_state_dir)
    item.set_defaults(func=run)
