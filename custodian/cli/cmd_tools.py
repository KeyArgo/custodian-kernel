"""custodian tools -- list and invoke governed Hermes skills."""
from __future__ import annotations

import json
import sys

from custodian.tools.registry import default_registry

BAND_COLOR = {"L0": "\033[2m", "L1": "\033[36m", "L2": "\033[32m", "L3": "\033[33m", "L4": "\033[31m"}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"


def cmd_tools_list(args) -> int:
    reg = default_registry().load()
    tools = reg.all()
    s = reg.summary()

    print(f"\n{BOLD}Custodian Tool Registry{RESET}  —  {s['total']} tools · {s['configured']} configured · {s['stubs']} stubs\n")

    current_band = None
    for t in tools:
        if t.band != current_band:
            current_band = t.band
            band_labels = {
                "L0": "L0  Read-only / free",
                "L1": "L1  Trivial autonomous (< $0.50)",
                "L2": "L2  Autonomous up to per-action cap",
                "L3": "L3  Always requires human approval",
                "L4": "L4  Unlimited — always escalates",
            }
            label = band_labels.get(t.band, t.band)
            color = BAND_COLOR.get(t.band, "")
            print(f"  {color}{BOLD}{label}{RESET}")

        status = "" if t.configured else f"  {DIM}[stub — set env vars to enable]{RESET}"
        cost = f"  ~${t.cost_usd:.2f}/call" if t.cost_usd else ""
        print(f"    {'✓' if t.configured else '○'}  {t.name:<32} {DIM}{t.description[:55]}{RESET}{cost}{status}")

    print(f"\n{DIM}Every tool call is checked against the current authority band before execution.{RESET}\n")
    return 0


def cmd_tools_run(args) -> int:
    if not args.tool:
        print("usage: custodian tools run <tool-name> [--key value ...]", file=sys.stderr)
        return 1

    reg = default_registry().load()
    tool = reg.get(args.tool)
    if not tool:
        available = [t.name for t in reg.all()]
        print(f"error: unknown tool '{args.tool}'", file=sys.stderr)
        print(f"available: {', '.join(available)}", file=sys.stderr)
        return 1

    kwargs = {}
    if args.kwargs:
        it = iter(args.kwargs)
        for k in it:
            key = k.lstrip("-").replace("-", "_")
            try:
                val = next(it)
            except StopIteration:
                val = "true"
            kwargs[key] = val

    result = tool.invoke(**kwargs)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


def cmd_tools_summary(args) -> int:
    reg = default_registry().load()
    s = reg.summary()
    print(json.dumps(s, indent=2))
    return 0
