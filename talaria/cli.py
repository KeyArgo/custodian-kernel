"""``talaria`` — the one command Hermes users need to learn.

Talaria wraps the credential broker (``warden``) and the guard-adapter
registry (``custodian.adapters``) under a single CLI, so a Hermes user
never has to know three tool names to get governed credentials and
guardrails working. Nothing here duplicates logic — every subcommand
delegates straight to the same code the standalone ``warden``/
``custodian adapters`` CLIs call.

    talaria vault add stripe_sk --env-var STRIPE_SECRET_KEY
    talaria vault grant stripe_sk --to skill:stripe-spend --max-band L2
    talaria adapters enable spend-sentinel
    talaria session status ./hermes-session.capsule.json
    talaria init ./hermes-session.yaml

``talaria vault ...`` and ``warden ...`` are the same broker underneath —
use whichever name you like; both work standalone too.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from custodian.cli import cmd_adapters
from custodian.cli._version import LazyVersionAction
from warden import cli as warden_cli
from warden.errors import WardenError

_SESSION_YAML_TEMPLATE = """\
goal: {goal}
band: L1
budget_usd: 10.00
constraints: []

tools:
  # allow: [http-get, stripe-spend]   # omit = every registered tool
  forbid: []

files:
  workspace: {workspace}
  skill_quarantine: {quarantine}

network:
  hosts: []

privacy:
  redact: []          # e.g. [email, phone, ssn, card]

guards:                # all default true; set false to drop one
  prompt_injection: true
  secret_leak: true
  repetition: true
  self_protection: true
  introspection: true
"""


def cmd_vault(args) -> int:
    """Forward every arg after `vault` straight to warden's own CLI."""
    return warden_cli.main(args.vault_args)


def _load_capsule(path_str: str):
    """Load a capsule or return None after printing a clean error —
    a corrupt/foreign JSON file must not surface as a raw traceback."""
    from talaria.capsule import SessionCapsule
    path = Path(path_str)
    if not path.exists():
        print(f"talaria: no session capsule at {path}", file=sys.stderr)
        return None
    try:
        return SessionCapsule.load(path)
    except Exception as e:
        print(f"talaria: {path} is not a readable session capsule "
              f"({type(e).__name__}: {e})", file=sys.stderr)
        return None


def cmd_session_status(args) -> int:
    capsule = _load_capsule(args.capsule_path)
    if capsule is None:
        return 1
    print(capsule.render_status())
    return 0


def cmd_session_anchor(args) -> int:
    capsule = _load_capsule(args.capsule_path)
    if capsule is None:
        return 1
    print(capsule.render_anchor())
    return 0


def cmd_init(args) -> int:
    path = Path(args.path)
    if path.exists() and not args.force:
        print(f"talaria: {path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1
    workspace = args.workspace or str(path.parent / "workspace")
    # json.dumps produces double-quoted, escaped strings — valid YAML
    # scalars even when the goal contains quotes/colons/newlines.
    path.write_text(_SESSION_YAML_TEMPLATE.format(
        goal=json.dumps(args.goal),
        workspace=json.dumps(workspace),
        quarantine=json.dumps(str(Path(workspace) / "skill-drafts")),
    ))
    print(f"wrote {path}")
    print(f"next: talaria vault init   # create the credential vault (if you don't have one)")
    print(f"      talaria adapters list   # see what guardrails are available")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="talaria",
        description="Talaria — the Hermes Agent + NemoClaw integration suite.",
    )
    p.add_argument("--version", action=LazyVersionAction,
                   fmt="%(prog)s {version} (custodian-kernel)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser(
        "vault",
        help="Manage credentials (same broker as the standalone `warden` command)",
        add_help=False,
    )
    sp.add_argument("vault_args", nargs=argparse.REMAINDER)
    sp.set_defaults(func=cmd_vault)

    # Same subcommand tree as `custodian adapters` — reused, not duplicated,
    # so the two never drift apart as the adapters surface grows.
    cmd_adapters.register(sub)

    sp = sub.add_parser("session", help="Inspect a Hermes session's governed state")
    ssub = sp.add_subparsers(dest="session_command", required=True)

    ssp = ssub.add_parser("status", help="One-line session status")
    ssp.add_argument("capsule_path")
    ssp.set_defaults(func=cmd_session_status)

    ssp = ssub.add_parser("anchor", help="Print the full re-anchoring block")
    ssp.add_argument("capsule_path")
    ssp.set_defaults(func=cmd_session_anchor)

    sp = sub.add_parser("init", help="Scaffold a session-policy.yaml")
    sp.add_argument("path", nargs="?", default="hermes-session.yaml")
    sp.add_argument("--goal", default="")
    sp.add_argument("--workspace", default=None)
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code = args.func(args)
        return code if isinstance(code, int) else 0
    except SystemExit as e:
        # cmd_vault forwards straight into warden.cli.main(), whose own
        # argparse instance calls sys.exit() directly on a malformed
        # subcommand (e.g. `talaria vault grant x` missing --to) — that
        # must come back as a return code like every other error here,
        # not escape as an uncaught exception from a function typed -> int.
        return e.code if isinstance(e.code, int) else 1
    except WardenError as e:
        print(f"talaria: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
