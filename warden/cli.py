"""``warden`` — the human's password/env manager for agent credentials.

Design rules for this CLI:

* **Values in, never out.** ``add``/``edit`` read values via getpass or
  stdin; no subcommand prints a secret value. Not ``list``, not
  ``show``, not errors, not ``--verbose``. The only way a value leaves
  the vault is ``warden exec`` egress into a child process env.
* Passphrase comes from ``WARDEN_PASSPHRASE``/``WARDEN_KEYFILE`` (for
  scripting) or an interactive prompt.
* Every state change is audited.

Examples::

    warden init
    warden add stripe_sk --profile prod --env-var STRIPE_SECRET_KEY
    warden list
    warden show stripe_sk                      # metadata only
    warden grant 'stripe*' --to skill:stripe-spend --max-band L2
    warden exec --with stripe_sk -- python bill.py
    warden exec --profile prod -- python agent.py
    warden audit verify
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

from warden.broker import Broker
from warden.errors import WardenError
from warden.refs import SecretRef
from warden.vault import Vault

CLI_REQUESTER = "user:cli"


def _open_vault(args) -> Vault:
    return Vault.open_from_env(path=args.vault, interactive=True)


def _broker(args) -> Broker:
    return Broker(_open_vault(args))


def _read_value(prompt: str, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    value = getpass.getpass(prompt)
    if not value:
        raise WardenError("empty value")
    return value


def cmd_init(args) -> int:
    if args.keyfile:
        key_path = Path(args.keyfile).expanduser()
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(os.urandom(32))
            print(f"generated keyfile {key_path} (mode 0600) — back it up securely")
        Vault.create(path=args.vault, keyfile=key_path)
    else:
        env_pp = os.environ.get("WARDEN_PASSPHRASE")
        if env_pp:
            # Non-interactive setup (CI/services): trust the env passphrase.
            Vault.create(path=args.vault, passphrase=env_pp)
        else:
            p1 = getpass.getpass("new vault passphrase: ")
            p2 = getpass.getpass("repeat: ")
            if p1 != p2:
                raise WardenError("passphrases do not match")
            Vault.create(path=args.vault, passphrase=p1)
    print(f"vault created at {args.vault or Vault.default_path()}")
    return 0


def cmd_add(args) -> int:
    vault = _open_vault(args)
    value = _read_value(f"value for {args.name}: ", args.stdin)
    ref = vault.add(args.name, value, kind=args.kind, profile=args.profile,
                    env_var=args.env_var, note=args.note or "", overwrite=args.force)
    Broker(vault).audit.append("add", args.name, CLI_REQUESTER, "-",
                               f"profile={args.profile}")
    print(f"stored {ref} (profile={args.profile})")
    return 0


def cmd_edit(args) -> int:
    vault = _open_vault(args)
    if args.rotate_value:
        value = _read_value(f"new value for {args.name}: ", args.stdin)
        vault.add(args.name, value, overwrite=True)
    vault.update_meta(args.name, profile=args.profile, env_var=args.env_var,
                      note=args.note)
    Broker(vault).audit.append("edit", args.name, CLI_REQUESTER, "-", "")
    print(f"updated warden://{args.name}")
    return 0


def cmd_rm(args) -> int:
    vault = _open_vault(args)
    vault.delete(args.name)
    Broker(vault).audit.append("delete", args.name, CLI_REQUESTER, "-", "")
    print(f"deleted warden://{args.name}")
    return 0


def cmd_list(args) -> int:
    vault = _open_vault(args)
    rows = list(vault.iter_meta(profile=args.profile))
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("(vault is empty)")
        return 0
    width = max(len(r["name"]) for r in rows)
    for r in rows:
        age = time.strftime("%Y-%m-%d", time.localtime(r["updated_at"]))
        print(f"warden://{r['name']:<{width}}  {r['profile']:<10} "
              f"{r['kind']:<8} → ${r['env_var']}  ({r['length']} chars, {age})")
    return 0


def cmd_show(args) -> int:
    vault = _open_vault(args)
    print(json.dumps(vault.meta(args.name), indent=2))
    return 0


def cmd_import_env(args) -> int:
    vault = _open_vault(args)
    names = vault.import_env_file(Path(args.file), profile=args.profile,
                                  overwrite=args.force)
    Broker(vault).audit.append("add", f"import:{args.file}", CLI_REQUESTER, "-",
                               f"count={len(names)}")
    for n in names:
        print(f"imported warden://{n}")
    print(f"\n{len(names)} entries imported. The plaintext file {args.file} "
          f"still exists — shred it when ready:  shred -u {args.file}")
    return 0


def cmd_grant(args) -> int:
    broker = _broker(args)
    g = broker.grant(args.pattern, args.to, max_band=args.max_band,
                     ttl_seconds=args.ttl, note=args.note or "")
    exp = f", expires in {int(args.ttl)}s" if args.ttl else ""
    print(f"granted {g.ref_pattern!r} → {g.requester} (≤{g.max_band}{exp})")
    return 0


def cmd_revoke(args) -> int:
    broker = _broker(args)
    removed = broker.revoke(args.pattern, args.to)
    print(f"revoked {removed} grant(s)")
    return 0


def cmd_grants(args) -> int:
    broker = _broker(args)
    grants = broker.grants.list()
    if not grants:
        print("(no grants — deny-by-default is in effect for all requesters)")
        return 0
    for g in grants:
        exp = time.strftime("%Y-%m-%d %H:%M", time.localtime(g.expires_at)) \
            if g.expires_at else "never"
        print(f"{g.ref_pattern:<24} → {g.requester:<28} ≤{g.max_band}  expires: {exp}")
    return 0


def cmd_exec(args) -> int:
    broker = _broker(args)
    refs = {}
    for spec in args.with_refs or []:
        # "stripe_sk" (use configured env var) or "stripe_sk=STRIPE_KEY"
        name, _, var = spec.partition("=")
        ref = SecretRef.parse(name)
        refs[var or broker.vault.meta(ref.name)["env_var"]] = ref
    proc = broker.spawn(args.cmd, refs, requester=CLI_REQUESTER, band="L0",
                        profile=args.profile, capture_output=False)
    return proc.returncode


def cmd_audit(args) -> int:
    broker = _broker(args)
    if args.action == "verify":
        n = broker.audit.verify()
        print(f"audit chain OK — {n} records verified")
        return 0
    for rec in broker.audit.records()[-args.tail:]:
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec["ts"]))
        print(f"{ts}  {rec['event']:<8} {rec['ref']:<24} {rec['requester']:<28} "
              f"{rec['band']:<3} {rec['detail']}")
    return 0


def cmd_rotate_master(args) -> int:
    vault = _open_vault(args)
    p1 = getpass.getpass("NEW vault passphrase: ")
    p2 = getpass.getpass("repeat: ")
    if p1 != p2:
        raise WardenError("passphrases do not match")
    vault.rotate_master(new_passphrase=p1)
    Broker(vault).audit.append("rotate", "-", CLI_REQUESTER, "-", "master key rotated")
    print("vault re-encrypted under new master key")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="warden",
        description="Credential broker for AI agents — the agent never sees the value.",
    )
    p.add_argument("--vault", type=Path, default=None,
                   help="vault path (default: ~/.warden/vault.warden, or $WARDEN_HOME)")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("init", help="create a new vault")
    sp.add_argument("--keyfile", help="use a random 32-byte keyfile instead of a passphrase")
    sp.set_defaults(fn=cmd_init)

    sp = sub.add_parser("add", help="store a secret (value prompted, never echoed)")
    sp.add_argument("name")
    sp.add_argument("--kind", default="secret",
                    choices=["secret", "env", "token", "password"])
    sp.add_argument("--profile", default="default")
    sp.add_argument("--env-var", default=None,
                    help="env var name used at injection (default: NAME uppercased)")
    sp.add_argument("--note", default=None)
    sp.add_argument("--stdin", action="store_true", help="read value from stdin")
    sp.add_argument("--force", action="store_true", help="overwrite existing entry")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("edit", help="update an entry's metadata and/or value")
    sp.add_argument("name")
    sp.add_argument("--rotate-value", action="store_true", help="prompt for a new value")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--env-var", default=None)
    sp.add_argument("--note", default=None)
    sp.add_argument("--stdin", action="store_true")
    sp.set_defaults(fn=cmd_edit)

    sp = sub.add_parser("rm", help="delete an entry")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_rm)

    sp = sub.add_parser("list", help="list entries (names + metadata, never values)")
    sp.add_argument("--profile", default=None)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("show", help="show one entry's metadata (never the value)")
    sp.add_argument("name")
    sp.set_defaults(fn=cmd_show)

    sp = sub.add_parser("import-env", help="import a .env file into the vault")
    sp.add_argument("file")
    sp.add_argument("--profile", default="default")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_import_env)

    sp = sub.add_parser("grant", help="allow a requester to resolve matching refs")
    sp.add_argument("pattern", help="ref name or glob, e.g. 'stripe/*'")
    sp.add_argument("--to", required=True,
                    help="exact requester id, e.g. skill:stripe-spend")
    sp.add_argument("--max-band", default="L2", choices=["L0", "L1", "L2", "L3", "L4"])
    sp.add_argument("--ttl", type=float, default=None, help="grant lifetime in seconds")
    sp.add_argument("--note", default=None)
    sp.set_defaults(fn=cmd_grant)

    sp = sub.add_parser("revoke", help="remove grants for (pattern, requester)")
    sp.add_argument("pattern")
    sp.add_argument("--to", required=True)
    sp.set_defaults(fn=cmd_revoke)

    sp = sub.add_parser("grants", help="list active grants")
    sp.set_defaults(fn=cmd_grants)

    sp = sub.add_parser("exec", help="run a command with secrets injected into its env")
    sp.add_argument("--with", dest="with_refs", action="append", metavar="NAME[=ENV_VAR]",
                    help="inject one secret (repeatable)")
    sp.add_argument("--profile", default=None, help="inject a whole profile")
    sp.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="command to run (prefix with --)")
    sp.set_defaults(fn=cmd_exec)

    sp = sub.add_parser("audit", help="inspect or verify the audit chain")
    sp.add_argument("action", nargs="?", default="tail", choices=["tail", "verify"])
    sp.add_argument("--tail", type=int, default=20)
    sp.set_defaults(fn=cmd_audit)

    sp = sub.add_parser("rotate-master", help="re-encrypt the vault under a new passphrase")
    sp.set_defaults(fn=cmd_rotate_master)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "cmd", None) and args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]
    try:
        return args.fn(args)
    except WardenError as e:
        print(f"warden: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
