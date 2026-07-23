"""Installer, doctor, and bridge CLI for governed Claude Code.

`setup` merges a fail-closed ``PreToolUse`` hook into a Claude Code
``settings.json`` so the harness enforces Custodian on every tool call. The
command is pinned to the exact interpreter that installed it (so a shell PATH
change can't silently swap in an ungoverned Python), and the merge is
idempotent and never clobbers unrelated settings.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .bridge import evaluate_tool
from .hook import main as hook_main

HOOK_MODULE = "custodian.claude_guard.hook"
# Stable marker so setup/doctor/uninstall can find *our* hook entry among any
# others the user has, regardless of the interpreter path baked into it.
HOOK_MARKER = "custodian.claude_guard.hook"
# "*" governs every tool. Reads/writes/tests still resolve to the autonomous
# band, so this is not a prompt on every call -- only genuinely consequential
# or unclassified (e.g. unknown MCP) tools escalate.
DEFAULT_MATCHER = "*"


def _hook_command(python: str | None = None) -> str:
    return f"{python or sys.executable} -m {HOOK_MODULE}"


def _settings_path(args: argparse.Namespace) -> Path:
    if getattr(args, "settings", None):
        return Path(args.settings).expanduser()
    if getattr(args, "project", False):
        return Path.cwd() / ".claude" / "settings.json"
    return Path.home() / ".claude" / "settings.json"


def _load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(
            f"refusing to modify unreadable/invalid settings file {path}: {exc}\n"
            "fix or remove it, then rerun setup"
        )
    if not isinstance(data, dict):
        raise SystemExit(f"refusing to modify {path}: top-level JSON is not an object")
    return data


def _our_entry(matcher: str, python: str | None = None) -> dict[str, Any]:
    return {
        "matcher": matcher,
        "hooks": [{
            "type": "command",
            "command": _hook_command(python),
            "timeout": 30,
        }],
    }


def _is_ours(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks", []) or []:
        if isinstance(hook, dict) and HOOK_MARKER in str(hook.get("command", "")):
            return True
    return False


def _write_atomic(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".custodian.tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def cmd_setup(args: argparse.Namespace) -> int:
    path = _settings_path(args)
    settings = _load_settings(path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit(f"refusing to modify {path}: existing 'hooks' is not an object")
    pre = hooks.setdefault("PreToolUse", [])
    if not isinstance(pre, list):
        raise SystemExit(f"refusing to modify {path}: existing 'hooks.PreToolUse' is not a list")

    kept = [e for e in pre if not _is_ours(e)]
    kept.append(_our_entry(args.matcher))
    hooks["PreToolUse"] = kept

    if args.dry_run:
        print(f"would install fail-closed Claude Code PreToolUse hook into: {path}")
        print(f"  matcher : {args.matcher}")
        print(f"  command : {_hook_command()}")
        return 0

    _write_atomic(path, settings)
    print(f"installed Custodian Claude guard: {path}")
    print(f"  matcher : {args.matcher}  (governs every tool call)")
    print(f"  command : {_hook_command()}")
    print("Restart Claude Code (or /hooks) so it re-reads settings.")
    print("Run guarded from a project subdirectory, not your bare home directory.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    path = _settings_path(args)
    problems: list[str] = []
    notes: list[str] = []
    settings = _load_settings(path)
    pre = (settings.get("hooks") or {}).get("PreToolUse") or []
    ours = [e for e in pre if _is_ours(e)] if isinstance(pre, list) else []
    if not ours:
        problems.append(f"no Custodian PreToolUse hook found in {path}; run setup")
    else:
        expected = _hook_command()
        installed = [h.get("command") for e in ours for h in (e.get("hooks") or [])]
        if expected not in installed:
            problems.append(
                f"installed hook interpreter differs from this one; rerun setup\n"
                f"    expected: {expected}\n    found:    {installed}"
            )
    if Path.cwd() == Path.home().resolve():
        notes.append("current directory is your home directory; the guard fails "
                     "closed on home-rooted workspaces -- run Claude from a project dir")

    for note in notes:
        print(f"NOTE: {note}")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"OK: Custodian Claude guard installed and interpreter-pinned ({path})")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    path = _settings_path(args)
    if not path.exists():
        print(f"nothing to remove: {path} does not exist")
        return 0
    settings = _load_settings(path)
    pre = (settings.get("hooks") or {}).get("PreToolUse")
    if not isinstance(pre, list):
        print("no Custodian hook present")
        return 0
    kept = [e for e in pre if not _is_ours(e)]
    if len(kept) == len(pre):
        print("no Custodian hook present")
        return 0
    settings["hooks"]["PreToolUse"] = kept
    _write_atomic(path, settings)
    print(f"removed Custodian Claude guard from {path}")
    return 0


def cmd_evaluate(_: argparse.Namespace) -> int:
    """Evaluate a bridge payload from stdin (parity with custodian-opencode)."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, TypeError):
        print(json.dumps({"verdict": "denied", "reason": "malformed Claude Code proposal"}))
        return 2
    decision = evaluate_tool(payload)
    print(json.dumps(decision, sort_keys=True))
    return 0 if decision.get("verdict") in {
        "autonomous", "approved", "escalation_required", "denied",
    } else 2


def cmd_hook(_: argparse.Namespace) -> int:
    """Run the PreToolUse hook (reads a Claude Code event from stdin)."""
    return hook_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="custodian-claude")
    sub = parser.add_subparsers(dest="command")

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", action="store_true",
                       help="use ./.claude/settings.json instead of the user-global file")
        p.add_argument("--settings", help="explicit settings.json path (overrides --project)")

    setup = sub.add_parser("setup", help="install the fail-closed PreToolUse hook")
    _common(setup)
    setup.add_argument("--matcher", default=DEFAULT_MATCHER,
                       help="tool matcher (default '*' governs all tools)")
    setup.add_argument("--dry-run", action="store_true")
    setup.set_defaults(func=cmd_setup)

    doctor = sub.add_parser("doctor", help="verify the installed hook and interpreter")
    _common(doctor)
    doctor.set_defaults(func=cmd_doctor)

    uninstall = sub.add_parser("uninstall", help="remove the Custodian hook from settings")
    _common(uninstall)
    uninstall.set_defaults(func=cmd_uninstall)

    evaluate = sub.add_parser("evaluate", help=argparse.SUPPRESS)
    evaluate.set_defaults(func=cmd_evaluate)
    hook = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook.set_defaults(func=cmd_hook)

    parser.set_defaults(func=lambda _a: (parser.print_help() or 0))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
