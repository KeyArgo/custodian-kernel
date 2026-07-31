"""Simple personal gate controls shared by all installed adapters."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from custodian.control.settings import ControlSettings, ControlSettingsStore
from custodian.control.gate_policy import GATES, MODES, SCOPES, GatePolicy, GateRule
from custodian.control.harness_capabilities import capabilities_for, known_harnesses


def _store(state_dir: str) -> ControlSettingsStore:
    return ControlSettingsStore(Path(state_dir) / "control-settings.json")


def describe(settings: ControlSettings) -> str:
    risk = (
        "monitor-only: detector findings are recorded but do not block; "
        "granular Ask/Block rules still apply"
        if settings.enforcement == "open"
        else "credential, destructive, production, money, and governance actions require approval"
    )
    notices = (
        "routine pass-through notices shown"
        if settings.visibility == "verbose"
        else "routine pass-through notices hidden; receipts still recorded"
    )
    result = (
        f"Enforcement: {settings.enforcement}\n"
        f"  {risk}\n"
        f"Visibility: {settings.visibility}\n"
        f"  {notices}"
    )
    if settings.harness_enforcement:
        result += "\nHarness presets:"
        for harness, mode in sorted(settings.harness_enforcement.items()):
            result += f"\n  {harness}: {mode}"
    return result


def run(args) -> int:
    store = _store(args.state_dir)
    current = store.load()
    if args.gate_command == "status":
        print(describe(current))
        rules = GatePolicy(Path(args.state_dir) / "gate-policy.json").list()
        print(f"Granular rules: {len(rules)}")
        for rule in rules:
            print(
                f"  {rule.gate}: {rule.mode} ({rule.scope}={rule.target}, "
                f"rule={rule.rule_id})"
            )
        return 0
    if args.gate_command == "set":
        policy = GatePolicy(Path(args.state_dir) / "gate-policy.json")
        rule = GateRule(
            gate=args.gate, mode=args.mode, scope=args.scope,
            target=args.target, harness=args.harness, tool=args.tool,
        )
        policy.add(rule)
        print(
            f"Saved {rule.gate}: {rule.mode} for "
            f"{rule.scope}={rule.target} (rule {rule.rule_id})."
        )
        print("Detection and receipts remain enabled.")
        return 0
    if args.gate_command == "capabilities":
        names = [args.harness] if args.harness else list(known_harnesses())
        for name in names:
            capabilities = capabilities_for(name)
            print(f"{capabilities.harness}:")
            print(f"  shared gates: {', '.join(sorted(capabilities.gates))}")
            specific = ", ".join(sorted(capabilities.harness_specific_gates)) or "none"
            print(f"  harness-specific gates: {specific}")
            print(f"  approval: {capabilities.approval_transport}")
            print(f"  allow notification: {capabilities.allow_notification}")
        return 0
    if args.gate_command == "open":
        harness = getattr(args, "harness", None)
        if harness:
            overrides = {**current.harness_enforcement, harness: "open"}
            store.save(replace(current, harness_enforcement=overrides))
            print(f"Open monitor mode enabled for harness {harness}.")
        else:
            store.save(replace(current, enforcement="open"))
            print("Open monitor mode enabled as the global default.")
        print("Detector findings are recorded; granular Ask/Block rules still apply.")
    elif args.gate_command == "protect":
        harness = getattr(args, "harness", None)
        if harness:
            overrides = {**current.harness_enforcement, harness: "protected"}
            store.save(replace(current, harness_enforcement=overrides))
            print(f"Protected mode enabled for harness {harness}.")
        else:
            store.save(replace(current, enforcement="protected"))
            print("Protected mode enabled as the global default.")
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
        ("open", "Monitor detector findings without blocking; granular gates still apply"),
        ("protect", "Require approval for high-risk action classes"),
    ):
        item = commands.add_parser(name, help=help_text)
        if name in {"open", "protect"}:
            item.add_argument(
                "--harness",
                help="override one harness (for example codex, claude, or opencode)",
            )
        item.add_argument("--state-dir", default=default_state_dir,
                          help="Custodian state directory")
        item.set_defaults(func=run)
    item = commands.add_parser(
        "notifications", help="Show or hide routine auto-approval notices"
    )
    item.add_argument("mode", choices=["verbose", "quiet"],
                      help="whether routine gate decisions are displayed")
    item.add_argument("--state-dir", default=default_state_dir,
                      help="Custodian state directory")
    item.set_defaults(func=run)
    item = commands.add_parser(
        "capabilities", help="Show shared and harness-specific gate support"
    )
    item.add_argument(
        "harness",
        nargs="?",
        help="Harness to inspect; omit to show every known harness",
    )
    item.add_argument(
        "--state-dir", default=default_state_dir, help="Custodian state directory"
    )
    item.set_defaults(func=run)
    item = commands.add_parser(
        "set", help="Set one granular gate to allow, ask, or block"
    )
    item.add_argument("gate", choices=sorted(GATES), help="Gate to configure")
    item.add_argument("mode", choices=sorted(MODES), help="Decision mode")
    item.add_argument(
        "--scope",
        choices=sorted(SCOPES),
        default="global",
        help="Policy scope used to match this rule",
    )
    item.add_argument("--target", default="*", help="Scope target or wildcard")
    item.add_argument("--harness", default="*", help="Harness name or wildcard")
    item.add_argument("--tool", default="*", help="Tool name or wildcard")
    item.add_argument(
        "--state-dir", default=default_state_dir, help="Custodian state directory"
    )
    item.set_defaults(func=run)
