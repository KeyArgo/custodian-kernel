"""``talaria`` — the one command Hermes users need to learn.

Talaria wraps the credential broker (``paladin``) and the guard-adapter
registry (``custodian.adapters``) under a single CLI, so a Hermes user
never has to know three tool names to get governed credentials and
guardrails working. Nothing here duplicates logic — every subcommand
delegates straight to the same code the standalone ``paladin``/
``custodian adapters`` CLIs call.

    talaria vault add stripe_sk --env-var STRIPE_SECRET_KEY
    talaria vault grant stripe_sk --to skill:stripe-spend --max-band L2
    talaria adapters enable spend-sentinel
    talaria session status ./hermes-session.capsule.json
    talaria init ./hermes-session.yaml

``talaria vault ...`` and ``paladin ...`` are the same broker underneath —
use whichever name you like; both work standalone too.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from custodian.cli import cmd_adapters
from custodian.cli._version import LazyVersionAction
from paladin import cli as paladin_cli
from paladin.errors import PaladinError

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
    """Forward every arg after `vault` straight to paladin's own CLI."""
    return paladin_cli.main(args.vault_args)


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


# ANSI colors for the denial-log timeline, keyed by adapter category.
_CAT_COLOR = {
    "security": "\033[31m", "money": "\033[32m", "privacy": "\033[35m",
    "guardrail": "\033[36m", "integration": "\033[33m",
}
_RESET = "\033[0m"
_DIM = "\033[2m"


def cmd_log(args) -> int:
    from talaria.denial_log import DenialLog
    from paladin.errors import AuditChainBrokenError

    log = DenialLog()

    if args.log_action == "verify":
        try:
            n = log.verify()
        except AuditChainBrokenError as e:
            print(f"talaria: denial log FAILED integrity check — {e}", file=sys.stderr)
            return 2
        print(f"denial log chain OK — {n} record(s) verified")
        return 0

    records = log.records()
    if args.tail:
        records = records[-args.tail:]

    if args.log_action == "export" or args.json:
        print(json.dumps(records, indent=2))
        return 0
    if args.csv:
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "event", "tool", "denied_by", "reason"])
        for r in records:
            w.writerow([r.get("ts"), r.get("event"), r.get("ref"),
                        r.get("requester"), r.get("detail")])
        print(buf.getvalue(), end="")
        return 0

    # Default: human timeline.
    if not records:
        print("No denied attempts logged yet. "
              "(This is the record of things the agent tried but wasn't allowed to do.)")
        return 0
    print(f"\nDenied agent attempts — {len(records)} record(s)\n")
    for r in records:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("ts", 0)))
        adapter = r.get("requester", "-")
        color = _CAT_COLOR.get(_adapter_category(adapter), "")
        event = r.get("event", "deny").upper()
        print(f"  {_DIM}{ts}{_RESET}  {color}{event}{_RESET}  "
              f"{r.get('ref', '-')}  {_DIM}(by {adapter}){_RESET}")
        print(f"      {r.get('detail', '')}")
    print()
    return 0


def cmd_dashboard(args) -> int:
    from talaria.dashboard import run_dashboard
    from talaria.denial_log import DenialLog
    from paladin.vault import Vault

    vault = None
    try:
        vault = Vault.open_from_env(interactive=True)
    except Exception as e:
        print(f"talaria: dashboard starting without an open vault "
              f"({type(e).__name__}: {e}) — the Vault section will show "
              f"an error, everything else still works", file=sys.stderr)

    denial_log = None
    try:
        denial_log = DenialLog()
    except Exception as e:
        print(f"talaria: denial log unavailable: {e}", file=sys.stderr)

    run_dashboard(host=args.host, port=args.port, vault=vault, denial_log=denial_log)
    return 0


def _adapter_category(adapter_name: str) -> str:
    try:
        from custodian.adapters.registry import AdapterRegistry
        for name, info in AdapterRegistry().available().items():
            if name == adapter_name:
                return info.get("category", "")
    except Exception:
        pass
    return ""


def _hermes_home() -> Path:
    """Resolve the active Hermes profile dir (where plugins live). Prefers
    HERMES_HOME, then the active-profile layout, then the plain default."""
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    base = Path("~/.hermes").expanduser()
    prof = base / "active_profile"
    if prof.exists():
        name = prof.read_text().strip()
        # A profile name is a single path segment, never a path itself.
        # pathlib's `/` operator lets an absolute string fully override
        # the left side (Path('~/.hermes/profiles') / '/etc' == Path('/etc')),
        # and '..' escapes the profiles dir the same way a shell would —
        # found in review. Reject anything shaped like either rather than
        # let unexpected active_profile contents redirect `talaria hermes
        # install`'s rmtree/copytree target outside ~/.hermes entirely.
        if name and os.sep not in name and "/" not in name and name not in ("..", "."):
            cand = base / "profiles" / name
            if cand.is_dir():
                return cand
    return base


def cmd_hermes(args) -> int:
    from talaria import policy as tpolicy

    if args.hermes_action == "install":
        src = Path(__file__).resolve().parent / "hermes_plugin"
        dest = _hermes_home() / "plugins" / "talaria-guard"
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("__pycache__"))
        print(f"✓ installed talaria-guard plugin → {dest}")

        # Starter policy (don't clobber an existing one).
        pol = tpolicy.default_policy_path()
        if not pol.exists():
            pol.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(pol.parent, 0o700)
            pol.write_text(tpolicy.STARTER_POLICY)
            print(f"✓ wrote starter policy → {pol}")
        else:
            print(f"• policy already exists → {pol} (left as-is)")

        # Create the vault if missing (keyfile-based, zero-friction).
        try:
            from paladin.vault import Vault
            vpath = Vault.default_path()
            if not vpath.exists():
                keyfile = vpath.parent / "vault.key"
                keyfile.parent.mkdir(parents=True, exist_ok=True)
                os.chmod(keyfile.parent, 0o700)
                if not keyfile.exists():
                    fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, "wb") as f:
                        f.write(os.urandom(32))
                Vault.create(path=vpath, keyfile=keyfile)
                print(f"✓ created credential vault → {vpath}")
                print(f"  (set PALADIN_KEYFILE={keyfile} in your shell to use it)")
            else:
                print(f"• vault already exists → {vpath} (left as-is)")
        except Exception as e:
            print(f"• vault setup skipped: {e}")

        print("\nNext:")
        print("  1. enable it in Hermes:  hermes plugins enable talaria-guard")
        print(f"  2. edit your rules:      {pol}")
        print("  3. run Hermes — every tool call is now governed.")
        print("  4. see blocked attempts: talaria log")
        return 0

    # status
    dest = _hermes_home() / "plugins" / "talaria-guard"
    pol = tpolicy.default_policy_path()
    print(f"plugin installed: {'yes' if dest.exists() else 'no'}  ({dest})")
    print(f"policy file:      {'yes' if pol.exists() else 'no'}  ({pol})")
    if pol.exists():
        p = tpolicy.load_policy()
        forbid_tools = p.get("tools", {}).get("forbid", [])
        forbid_paths = p.get("paths", {}).get("forbid", [])
        print(f"forbidden tools:  {forbid_tools or '(none)'}")
        print(f"forbidden paths:  {forbid_paths or '(none)'}")
        print(f"denial logging:   {'on' if p.get('log_denials', True) else 'off'}")
    try:
        n = 0
        from talaria.denial_log import DenialLog
        dl = DenialLog()
        if dl.path.exists():
            n = len(dl.records())
        print(f"denials logged:   {n}  (talaria log to view)")
    except Exception:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="talaria",
        description="Talaria — the Hermes Agent + NemoClaw integration suite.",
    )
    p.add_argument("--version", action=LazyVersionAction,
                   fmt="%(prog)s {version}")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser(
        "vault",
        help="Manage credentials (same broker as the standalone `paladin` command)",
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

    sp = sub.add_parser(
        "log",
        help="Show denied agent attempts (what it tried but wasn't allowed to do)",
    )
    sp.add_argument("log_action", nargs="?", default="show",
                    choices=["show", "verify", "export"],
                    help="show timeline (default), verify chain integrity, or export JSON")
    sp.add_argument("--tail", type=int, default=None, help="only the last N records")
    sp.add_argument("--json", action="store_true", help="machine-readable JSON")
    sp.add_argument("--csv", action="store_true", help="CSV export")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser(
        "hermes",
        help="Install/inspect the Hermes Agent plugin (one-command onboarding)",
    )
    sp.add_argument("hermes_action", nargs="?", default="status",
                    choices=["install", "status"],
                    help="install the plugin + starter policy + vault, or show status")
    sp.set_defaults(func=cmd_hermes)

    sp = sub.add_parser(
        "dashboard",
        help="Local web UI: denial log, vault entries, and policy toggles in one place",
    )
    sp.add_argument("--host", default="127.0.0.1",
                    help="bind address (default 127.0.0.1 — not exposed off this machine)")
    sp.add_argument("--port", type=int, default=8765)
    sp.set_defaults(func=cmd_dashboard)

    return p


def main(argv=None) -> int:
    try:
        from custodian._encoding import force_utf8_io
        force_utf8_io()
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    try:
        code = args.func(args)
        return code if isinstance(code, int) else 0
    except SystemExit as e:
        # cmd_vault forwards straight into paladin.cli.main(), whose own
        # argparse instance calls sys.exit() directly on a malformed
        # subcommand (e.g. `talaria vault grant x` missing --to) — that
        # must come back as a return code like every other error here,
        # not escape as an uncaught exception from a function typed -> int.
        return e.code if isinstance(e.code, int) else 1
    except PaladinError as e:
        print(f"talaria: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
