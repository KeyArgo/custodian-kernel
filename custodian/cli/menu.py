"""Interactive menu for the ``custodian`` CLI — the operator's front door.

Same design as paladin's menu: it never re-implements a command, it asks
plain-language questions, builds the argv the CLI already accepts, and hands it
to ``custodian.cli.main.main``. One code path per action, every guarantee of
the real command preserved.

Launched by ``custodian menu``, or by running ``custodian`` with no arguments
in an interactive terminal.
"""
from __future__ import annotations

import sys


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        return input(f"{label}{suffix}: ").strip() or default
    except (EOFError, KeyboardInterrupt):
        print()
        raise _Back()


class _Back(Exception):
    pass


def _choose(title: str, options: list[tuple[str, str]]) -> str | None:
    print(f"\n{title}")
    for i, (_k, label) in enumerate(options, 1):
        print(f"  {i}) {label}")
    print("  0) back / quit")
    while True:
        try:
            raw = input("choose: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if raw in ("0", "q", "quit", "exit", ""):
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print("  (enter a number from the list)")


def _run(argv: list[str]) -> None:
    from custodian.cli.main import main
    try:
        rc = main(argv)
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 1
    if rc not in (0, None):
        print("  (command reported an issue — see the message above)")


# -- actions ------------------------------------------------------------------

def _act_status() -> None:
    _run(["status"])


def _act_request() -> None:
    amount = _prompt("amount in USD (e.g. 5.00)")
    if not amount:
        return
    desc = _prompt("what is it for?")
    if not desc:
        return
    _run(["request", "--amount", amount, "--description", desc])


def _act_audit() -> None:
    _run(["audit"])


def _act_kill() -> None:
    by = _prompt("your name/id (for the record)")
    reason = _prompt("reason (optional)")
    argv = ["kill", "--by", by or "operator"]
    if reason:
        argv += ["--reason", reason]
    _run(argv)


def _act_resume() -> None:
    by = _prompt("your name/id (for the record)")
    _run(["resume", "--by", by or "operator"])


def _act_init() -> None:
    where = _prompt("directory to scaffold a new workspace in", "myagent")
    _run(["init", "--dir", where])


def _act_tools() -> None:
    _run(["tools", "list"])


def _act_adapters() -> None:
    _run(["adapters", "list"])


def _act_guide() -> None:
    _run(["guide"])


_ACTIONS = [
    ("status", "Show current authority state (bands, caps, spend)"),
    ("request", "Ask the kernel to decide on a spend"),
    ("audit", "View the audit log"),
    ("kill", "Engage the kill switch (stop everything)"),
    ("resume", "Release the kill switch"),
    ("tools", "List governed tools"),
    ("adapters", "List guard adapters"),
    ("init", "Scaffold a new workspace"),
    ("guide", "Guided walkthrough for first-time users"),
]

_DISPATCH = {
    "status": _act_status, "request": _act_request, "audit": _act_audit,
    "kill": _act_kill, "resume": _act_resume, "tools": _act_tools,
    "adapters": _act_adapters, "init": _act_init, "guide": _act_guide,
}


def run_menu() -> int:
    print("=" * 56)
    print("  Custodian — authority & spend governance")
    print("=" * 56)
    while True:
        choice = _choose("What would you like to do?", _ACTIONS)
        if choice is None:
            print("bye.")
            return 0
        try:
            _DISPATCH[choice]()
        except _Back:
            continue
        except KeyboardInterrupt:
            print("\n(cancelled)")
            continue
