"""Doctor and JSON bridge for the governed Hermes adapter.

``custodian-hermes evaluate`` reads one normalized proposal on stdin and
prints the shared engine's decision -- the same path the in-process Hermes
plugin drives, useful for integration tests and non-plugin harnesses.

``custodian-hermes doctor`` verifies the OSS artifact only: the kernel and
Hermes adapter import, the contract version, that the repository-owned
plugin directory ships with the installed package, and that the operator
state directory is writable. It deliberately does NOT inspect or modify any
Hermes profile -- operator deployment state is out of scope for this
package and is verified by the operator's own doctor tooling.
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources

from custodian.guards.codex.mcp_server import _state_dir

from .bridge import evaluate_tool
from .contract import HERMES_GUARD_CONTRACT_VERSION


def cmd_evaluate(_: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, TypeError):
        print(json.dumps({"verdict": "denied", "reason": "malformed Hermes proposal"}))
        return 2
    decision = evaluate_tool(payload)
    print(json.dumps(decision, sort_keys=True))
    if decision.get("verdict") not in {"autonomous", "approved", "escalation_required", "denied"}:
        return 2
    return 0


def cmd_doctor(_: argparse.Namespace) -> int:
    problems: list[str] = []
    try:
        from custodian.guards.hermes import HermesGuardRuntime  # noqa: F401
    except Exception as exc:
        problems.append(f"hermes_guard import failed: {exc}")
    try:
        plugin_dir = resources.files("custodian.guards.hermes.plugin")
        if not (plugin_dir / "plugin.yaml").is_file():
            problems.append("plugin manifest missing from installed package")
    except Exception as exc:
        problems.append(f"plugin artifact unreadable: {exc}")
    try:
        state = _state_dir()
        state.mkdir(parents=True, exist_ok=True)
        probe = state / ".doctor-write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        problems.append(f"state directory not writable: {exc}")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"OK: custodian-hermes contract v{HERMES_GUARD_CONTRACT_VERSION} wired to the shared engine")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="custodian-hermes")
    sub = parser.add_subparsers(dest="command")
    doctor = sub.add_parser("doctor", help="verify the OSS Hermes adapter artifact")
    doctor.set_defaults(func=cmd_doctor)
    evaluate = sub.add_parser("evaluate", help=argparse.SUPPRESS)
    evaluate.set_defaults(func=cmd_evaluate)
    parser.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
