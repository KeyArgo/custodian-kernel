"""custodian adapters -- manage guard adapters (money/security/privacy/guardrail)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from custodian.adapters.registry import AdapterLoadError, AdapterRegistry

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

CATEGORY_COLOR = {
    "money": "\033[32m", "security": "\033[31m",
    "privacy": "\033[35m", "guardrail": "\033[36m", "integration": "\033[33m",
}


def _registry(args) -> AdapterRegistry:
    return AdapterRegistry(adapters_dir=getattr(args, "adapters_dir", None))


def cmd_adapters_list(args) -> int:
    reg = _registry(args)
    available = reg.available()
    enabled_names = {e["name"] for e in reg.enabled()}
    if getattr(args, "json", False):
        print(json.dumps({"available": available,
                          "enabled": sorted(enabled_names)}, indent=2))
        return 0

    print(f"\n{BOLD}Custodian Guard Adapters{RESET}  —  "
          f"{len(available)} available · {len(enabled_names)} enabled\n")
    by_cat: dict[str, list[dict]] = {}
    for info in available.values():
        by_cat.setdefault(info.get("category", "?"), []).append(info)
    for cat in sorted(by_cat):
        color = CATEGORY_COLOR.get(cat, "")
        print(f"  {color}{BOLD}{cat}{RESET}")
        for info in sorted(by_cat[cat], key=lambda i: i["name"]):
            mark = "●" if info["name"] in enabled_names else "○"
            doc = info.get("doc", "")
            print(f"    {mark} {info['name']:<28} {DIM}{doc}{RESET}")
    print(f"\n  {DIM}● enabled · ○ available — "
          f"`custodian adapters enable <name>` to turn one on{RESET}\n")
    return 0


def cmd_adapters_enable(args) -> int:
    reg = _registry(args)
    config = json.loads(args.config) if args.config else None
    try:
        reg.enable(args.name, config=config)
    except AdapterLoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"enabled {args.name}" + (f" with config {config}" if config else ""))
    return 0


def cmd_adapters_disable(args) -> int:
    if _registry(args).disable(args.name):
        print(f"disabled {args.name}")
        return 0
    print(f"{args.name} was not enabled")
    return 1


def cmd_adapters_install(args) -> int:
    try:
        rec = _registry(args).install(Path(args.path))
    except AdapterLoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"installed {rec['name']} ({rec['category']}) — "
          f"sha256 pinned {rec['sha256'][:16]}…")
    print(f"enable it with: custodian adapters enable {rec['name']}")
    return 0


def cmd_adapters_check(args) -> int:
    """Dry-run the enabled pipeline against a sample action."""
    from custodian.adapters.base import ActionContext
    reg = _registry(args)
    try:
        pipeline = reg.load_pipeline()
    except AdapterLoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    ctx = ActionContext(
        skill=args.skill,
        args=json.loads(args.args) if args.args else {},
        band=args.band,
        cost_usd=args.cost,
        description=args.description or "",
    )
    result = pipeline.run_pre(ctx)
    print(f"{'ALLOW' if result.allowed else 'DENY'} — {result.summary()}")
    return 0 if result.allowed else 2


def register(sub) -> None:
    """Attach the `adapters` subcommand tree to the main parser."""
    parser = sub.add_parser(
        "adapters",
        help="Manage guard adapters (money, security, privacy, guardrail)",
        description=(
            "Guard adapters run before and after every governed action. "
            "Built-ins cover spend anomalies, prompt injection, secret leaks, "
            "PII, context anchoring, loop breaking, tool confabulation, and "
            "scope fencing. Local adapter files install hash-pinned: if the "
            "file changes after install, it refuses to load."
        ),
    )
    asub = parser.add_subparsers(dest="adapters_command", required=True)

    sp = asub.add_parser("list", help="List available and enabled adapters")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_adapters_list)

    sp = asub.add_parser("enable", help="Enable an adapter")
    sp.add_argument("name")
    sp.add_argument("--config", help="JSON config object for the adapter")
    sp.set_defaults(func=cmd_adapters_enable)

    sp = asub.add_parser("disable", help="Disable an adapter")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_adapters_disable)

    sp = asub.add_parser("install", help="Install a local adapter file (hash-pinned)")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_adapters_install)

    sp = asub.add_parser("check", help="Dry-run the enabled pipeline against a sample action")
    sp.add_argument("skill")
    sp.add_argument("--args", help="JSON dict of tool arguments")
    sp.add_argument("--band", default="L0")
    sp.add_argument("--cost", type=float, default=0.0)
    sp.add_argument("--description", default="")
    sp.set_defaults(func=cmd_adapters_check)
