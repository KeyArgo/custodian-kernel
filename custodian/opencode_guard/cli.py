"""Installer, doctor, wrapper, and JSON bridge for governed OpenCode."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .bridge import evaluate_tool
from .plugin import PLUGIN_VERSION, plugin_source


def _plugin_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "opencode" / "plugins" / "custodian-guard.js"


def cmd_evaluate(_: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, TypeError):
        print(json.dumps({"verdict": "denied", "reason": "malformed OpenCode proposal"}))
        return 2
    decision = evaluate_tool(payload)
    print(json.dumps(decision, sort_keys=True))
    return 0 if decision.get("verdict") in {"autonomous", "approved", "escalation_required", "denied"} else 2


def cmd_setup(args: argparse.Namespace) -> int:
    path = _plugin_path()
    source = plugin_source()
    if args.dry_run:
        print(f"would install fail-closed OpenCode hook: {path}")
        print(f"interpreter: {sys.executable}")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    print(f"installed Custodian OpenCode guard: {path}")
    print("Use `custodian-opencode run ...` or `custodian-opencode`.")
    print("Direct `opencode --pure` disables plugins and is intentionally not a governed launch.")
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    path = _plugin_path()
    expected = plugin_source()
    problems = []
    if not shutil.which("opencode"):
        problems.append("opencode executable not found")
    if not path.is_file():
        problems.append(f"guard plugin missing: {path}")
    elif path.read_text(encoding="utf-8") != expected:
        problems.append("guard plugin is stale or modified; rerun setup")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"OK: OpenCode guard v{PLUGIN_VERSION} is installed and interpreter-pinned")
    print("OK: governed launcher rejects --pure")
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    if not shutil.which("opencode"):
        print("opencode is not installed or not on PATH", file=sys.stderr)
        return 127
    forwarded = list(args.arguments)
    if "--pure" in forwarded:
        print("refusing --pure: it disables the Custodian enforcement plugin", file=sys.stderr)
        return 2
    if cmd_doctor(argparse.Namespace()) != 0:
        print("OpenCode launch denied; run `custodian-opencode setup`", file=sys.stderr)
        return 1
    env = dict(os.environ)
    env["CUSTODIAN_GOVERNED_HARNESS"] = "opencode"
    return subprocess.call(["opencode", *forwarded], env=env)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="custodian-opencode")
    sub = parser.add_subparsers(dest="command")
    setup = sub.add_parser("setup", help="install the fail-closed global OpenCode hook")
    setup.add_argument("--dry-run", action="store_true")
    setup.set_defaults(func=cmd_setup)
    doctor = sub.add_parser("doctor", help="verify the installed hook and interpreter")
    doctor.set_defaults(func=cmd_doctor)
    evaluate = sub.add_parser("evaluate", help=argparse.SUPPRESS)
    evaluate.set_defaults(func=cmd_evaluate)
    parser.set_defaults(func=cmd_launch)
    return parser


def main(argv: list[str] | None = None) -> int:
    args, unknown = build_parser().parse_known_args(argv)
    if getattr(args, "command", None) is None:
        args.arguments = unknown
    elif unknown:
        build_parser().error("unrecognized arguments: " + " ".join(unknown))
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
