"""``paladin`` — the human's password/env manager for agent credentials.

Design rules for this CLI:

* **Values in, never out.** ``add``/``edit`` read values via getpass or
  stdin; no subcommand prints a secret value. Not ``list``, not
  ``show``, not errors, not ``--verbose``. The only way a value leaves
  the vault is ``paladin exec`` egress into a child process env.
* Passphrase comes from ``PALADIN_PASSPHRASE``/``PALADIN_KEYFILE`` (for
  scripting) or an interactive prompt.
* Every state change is audited.

Examples::

    paladin init
    paladin add stripe_sk --profile prod --env-var STRIPE_SECRET_KEY
    paladin import discover                     # where do credentials live?
    paladin import env ~/projects --recursive   # bulk-import every .env*
    paladin import csv ~/Downloads/export.csv   # a password-manager export
    paladin import json secrets.json --dry-run  # preview a secrets dump
    paladin import bitwarden --search "api key"
    paladin list
    paladin show stripe_sk                      # metadata only
    paladin grant 'stripe*' --to skill:stripe-spend --max-band L2
    paladin exec --with stripe_sk -- python bill.py
    paladin exec --profile prod -- python agent.py
    paladin audit verify
    paladin backup                              # encrypted backup, one file
    paladin restore backups/paladin-backup-20260716-120000.zip
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path

from paladin._prompt import read_secret
from paladin.broker import Broker
from paladin.errors import PaladinError
from paladin.refs import SecretRef
from paladin.vault import Vault

CLI_REQUESTER = "user:cli"


def _open_vault(args) -> Vault:
    return Vault.open_from_env(path=args.vault, interactive=True)


def _broker(args) -> Broker:
    return Broker(_open_vault(args))


def _read_value(prompt: str, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    value = read_secret(prompt)
    if not value:
        raise PaladinError("empty value")
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
        env_pp = os.environ.get("PALADIN_PASSPHRASE")
        if env_pp:
            # Non-interactive setup (CI/services): trust the env passphrase.
            Vault.create(path=args.vault, passphrase=env_pp)
        else:
            p1 = read_secret("new vault passphrase: ")
            p2 = read_secret("repeat: ")
            if p1 != p2:
                raise PaladinError("passphrases do not match")
            Vault.create(path=args.vault, passphrase=p1)
    print(f"vault created at {args.vault or Vault.default_path()}")
    print()
    print("Next steps:")
    print("  paladin add my_api_key        store your first secret")
    print("  paladin list                  see what's stored (never the values)")
    print("  paladin backup                save an encrypted backup — do this")
    print("                                once you've added real secrets")
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
    print(f"updated paladin://{args.name}")
    return 0


def cmd_rm(args) -> int:
    vault = _open_vault(args)
    vault.delete(args.name)
    Broker(vault).audit.append("delete", args.name, CLI_REQUESTER, "-", "")
    print(f"deleted paladin://{args.name}")
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
        print(f"paladin://{r['name']:<{width}}  {r['profile']:<10} "
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
        print(f"imported paladin://{n}")
    print(f"\n{len(names)} entries imported. The plaintext file {args.file} "
          f"still exists — shred it when ready:  shred -u {args.file}")
    return 0


def _print_import_report(report, as_json: bool) -> None:
    d = report.to_dict()
    if as_json:
        print(json.dumps(d, indent=2))
        return
    verb = "would import" if report.dry_run else "imported"
    print(f"{verb} {d['imported_count']} entr"
          f"{'y' if d['imported_count'] == 1 else 'ies'}")
    for e in report.imported:
        flag = f"  ⚠ {','.join(e['flags'])}" if e["flags"] else ""
        print(f"  paladin://{e['name']:<28} {e['kind']:<9} ({e['source']}){flag}")
    if report.skipped_existing:
        print(f"skipped {len(report.skipped_existing)} already in the vault: "
              f"{', '.join(report.skipped_existing[:8])}"
              f"{' …' if len(report.skipped_existing) > 8 else ''}")
    if report.skipped_invalid:
        print(f"skipped {len(report.skipped_invalid)} with unusable names/values")
    if report.flagged:
        print()
        print(f"⚠ {len(report.flagged)} entr"
              f"{'y' if len(report.flagged) == 1 else 'ies'} came from files "
              f"exposed to git (tracked or not ignored).")
        print("  Vaulting them does not un-expose them — rotate those "
              "credentials and delete/gitignore the files.")
    if not report.dry_run and report.imported:
        print()
        print("Check them:  paladin list")


def cmd_import(args) -> int:
    from paladin import importer as imp

    if args.source == "discover":
        report = imp.discover()
        if args.json:
            print(json.dumps(report, indent=2))
            return 0
        print("Where credentials live on this machine (nothing was imported):\n")
        if report["env_files"]:
            print(".env files:")
            for f in report["env_files"]:
                flag = f"  ⚠ {','.join(f['flags'])}" if f["flags"] else ""
                print(f"  {f['path']}  ({f['entries']} entries){flag}")
                print(f"      → {f['import_with']}")
        if report["shell_rc_exports"]:
            print("shell-rc exports (credential-looking names):")
            for f in report["shell_rc_exports"]:
                print(f"  {f['path']}:  {', '.join(f['names'][:6])}"
                      f"{' …' if len(f['names']) > 6 else ''}")
                print(f"      → {f['import_with']}")
        if report.get("export_files"):
            print("password-manager exports (CSV/JSON in Downloads/Desktop/here):")
            for f in report["export_files"]:
                flag = f"  ⚠ {','.join(f['flags'])}" if f["flags"] else ""
                print(f"  {f['path']}  [{f['type']}]{flag}")
                print(f"      → {f['import_with']}")
        for label, key in (("Bitwarden", "bitwarden"), ("1Password", "onepassword")):
            st = report[key]
            if not st["installed"]:
                print(f"{label}: CLI not installed")
            elif not st.get("unlocked", st.get("signed_in")):
                print(f"{label}: installed but locked — {st['hint']}")
            else:
                print(f"{label}: ready → {st['import_with']}")
        if not report["env_files"] and not report["shell_rc_exports"]:
            print("no .env files or credential-looking shell exports found "
                  "in ~ or the current directory")
        return 0

    if args.source == "env":
        if not args.path:
            raise PaladinError("`paladin import env` needs a path: a .env file "
                               "or a directory to scan")
        root = Path(args.path).expanduser()
        if not root.exists():
            raise PaladinError(f"no such file or directory: {root}")
        files = imp.collect_env_files(root, pattern=args.pattern,
                                      recursive=args.recursive)
        if not files:
            raise PaladinError(f"no files matching {args.pattern!r} under {root}")
        candidates = [c for f in files for c in imp.candidates_from_env(f)]
        source_desc = f"env:{root}"
    elif args.source in ("csv", "json"):
        if not args.path:
            raise PaladinError(f"`paladin import {args.source}` needs a path to "
                               f"a .{args.source} file")
        fpath = Path(args.path).expanduser()
        if not fpath.is_file():
            raise PaladinError(f"no such file: {fpath}")
        reader = (imp.candidates_from_csv if args.source == "csv"
                  else imp.candidates_from_json)
        candidates = reader(fpath)
        source_desc = f"{args.source}:{fpath}"
    elif args.source == "bitwarden":
        candidates = imp.bitwarden_candidates(search=args.search,
                                              folder=args.folder)
        source_desc = "bitwarden"
    elif args.source == "1password":
        candidates = imp.onepassword_candidates(vault=args.from_vault,
                                                search=args.search)
        source_desc = "1password"
    else:  # pragma: no cover - argparse restricts choices
        raise PaladinError(f"unknown source {args.source!r}")

    vault = _open_vault(args)
    report = imp.import_candidates(
        vault, candidates, profile=args.profile, dry_run=args.dry_run,
        skip_existing=not args.overwrite)
    if not args.dry_run:
        Broker(vault).audit.append(
            "add", f"import:{source_desc}", CLI_REQUESTER, "-",
            f"count={len(report.imported)} skipped={len(report.skipped_existing)}")
    _print_import_report(report, args.json)
    return 0


def cmd_grant(args) -> int:
    broker = _broker(args)
    g = broker.grant(args.pattern, args.to, max_band=args.max_band,
                     ttl_seconds=args.ttl, note=args.note or "",
                     allowed_hosts=args.host, methods=args.method,
                     path_prefix=args.path_prefix or "")
    exp = f", expires in {int(args.ttl)}s" if args.ttl else ""
    scope = ""
    if args.host or args.method or args.path_prefix:
        scope = (f" [hosts:{','.join(args.host) if args.host else '*'}"
                 f" methods:{','.join(args.method) if args.method else '*'}"
                 f" path:{args.path_prefix or '*'}]")
    print(f"granted {g.ref_pattern!r} → {g.requester} (≤{g.max_band}{exp}){scope}")
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
    if args.sandbox:
        return _cmd_exec_sandboxed(args, broker)
    refs = {}
    for spec in args.with_refs or []:
        # "stripe_sk" (use configured env var) or "stripe_sk=STRIPE_KEY"
        name, _, var = spec.partition("=")
        ref = SecretRef.parse(name)
        refs[var or broker.vault.meta(ref.name)["env_var"]] = ref
    proc = broker.spawn(args.cmd, refs, requester=CLI_REQUESTER, band="L0",
                        profile=args.profile, capture_output=False)
    return proc.returncode


def _cmd_exec_sandboxed(args, broker) -> int:
    """Network-isolated egress mode: the child never gets a secret in its
    env. It reaches the outside world only through the Paladin gateway,
    using paladin.egress_client. --with names the refs it may use."""
    from paladin.sandbox import spawn_sandboxed
    from paladin.errors import SandboxUnavailableError
    allow_refs = set()
    for spec in args.with_refs or []:
        allow_refs.add(SecretRef.parse(spec.partition("=")[0]).name)
    try:
        proc = spawn_sandboxed(
            args.cmd, broker, requester=args.as_requester, band=args.band,
            allow_refs=allow_refs or None, capture_output=False,
            allow_unsandboxed=args.allow_unsandboxed,
        )
    except SandboxUnavailableError as e:
        print(f"paladin: {e}", file=sys.stderr)
        return 1
    return proc.returncode


def cmd_doctor(args) -> int:
    """Report whether the hardened, network-isolated egress sandbox is
    available here — so operators know when the strong 'credential never
    enters the process' guarantee applies vs. when Paladin will fail
    closed."""
    from paladin.sandbox import bwrap_path, sandbox_available
    bw = bwrap_path()
    ok = sandbox_available()
    print(f"bwrap:              {bw or '(not found)'}")
    print(f"sandbox available:  {'yes' if ok else 'no'}")
    if ok:
        print("→ `paladin exec --sandbox` gives a network-isolated child that "
              "reaches nothing but the Paladin egress gateway.")
    else:
        print("→ sandboxed egress will FAIL CLOSED (install bubblewrap and "
              "enable unprivileged user namespaces to use --sandbox).")
    return 0 if ok else 1


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


def _plural(n: int, word: str = "entry") -> str:
    if word == "entry":
        return f"{n} entry" if n == 1 else f"{n} entries"
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def cmd_backup(args) -> int:
    from paladin import backup as bk

    src = Path(args.vault).expanduser() if args.vault else Vault.default_path()
    if not src.exists():
        raise PaladinError(
            f"no vault at {src} — run `paladin init` first (nothing to back up yet)")

    # Opening the vault IS the proof the backup will be restorable: if the
    # passphrase (or keyfile) the user has right now can't open it, that must
    # surface here — while they're at the keyboard — not months from now
    # during a disaster recovery.
    vault = Vault.open_from_env(path=src, interactive=True)
    try:
        dest = bk.resolve_backup_path(args.dest)
        if dest.exists() and args.force:
            dest.unlink()
        info = bk.create_backup(vault, dest)
    finally:
        vault.close()

    audit_note = (
        f" + audit trail ({_plural(info.audit_records, 'record')})"
        if info.has_audit else "")
    print(f"backed up {_plural(info.entry_count)}{audit_note}")
    print(f"  → {info.path}")
    print()
    print("The backup is ENCRYPTED — it can only be opened with your")
    print("passphrase (or keyfile), which is NOT inside it. Keep them apart:")
    print("the file alone reveals nothing, the passphrase alone opens nothing.")
    if args.dest is None:
        print()
        print("NOTE: this backup lives on the SAME computer as the vault. For")
        print("real protection, copy it to a USB drive, another machine, or")
        print("cloud storage.")
    print()
    print(f"To restore (here or on another machine):")
    print(f"  paladin restore \"{info.path}\"")
    return 0


def cmd_restore(args) -> int:
    from paladin import backup as bk

    dest = Path(args.vault).expanduser() if args.vault else Vault.default_path()
    src = Path(args.source).expanduser()

    # Passphrase/keyfile for verifying the backup opens. Interactive prompt
    # mirrors open_from_env's behavior so `paladin restore` feels identical
    # to every other command.
    keyfile = os.environ.get("PALADIN_KEYFILE") or None
    passphrase = os.environ.get("PALADIN_PASSPHRASE")
    if keyfile is None and passphrase is None:
        passphrase = read_secret("vault passphrase: ")

    info = bk.restore_backup(
        src, dest, force=args.force, passphrase=passphrase,
        keyfile=Path(keyfile) if keyfile else None)

    audit_note = (
        f" + audit trail ({_plural(info.audit_records, 'record')})"
        if info.has_audit else "")
    print(f"restored {_plural(info.entry_count)}{audit_note}")
    print(f"  → {info.path}")
    if args.force:
        print(f"  (anything replaced was saved next to it as *.pre-restore)")
    print()
    print("Check it: paladin list")
    return 0


def cmd_rotate_master(args) -> int:
    vault = _open_vault(args)
    p1 = read_secret("NEW vault passphrase: ")
    p2 = read_secret("repeat: ")
    if p1 != p2:
        raise PaladinError("passphrases do not match")
    vault.rotate_master(new_passphrase=p1)
    Broker(vault).audit.append("rotate", "-", CLI_REQUESTER, "-", "master key rotated")
    print("vault re-encrypted under new master key")
    print()
    print("IMPORTANT: backups made BEFORE this rotation still require your OLD")
    print("passphrase. If you no longer remember it, they are unrecoverable —")
    print("make a fresh backup now:  paladin backup")
    return 0


def _pkg_version() -> str:
    try:
        from importlib.metadata import version
        return version("custodian-kernel")
    except Exception:
        return "unknown"


class _LazyVersionAction(argparse.Action):
    """Like argparse's built-in 'version' action, but only computes the
    version string when --version is actually passed — a plain
    version=f"...{_pkg_version()}" is evaluated at add_argument() time,
    i.e. on every single `paladin` invocation, not just `--version`.

    Deliberately self-contained rather than imported from custodian.cli:
    paladin is a standalone package with zero dependency on custodian (see
    paladin/__init__.py's module docstring) and this must not become its
    first one. custodian's own CLI and talaria (which already depends on
    both) share an identical helper at custodian.cli._version instead."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS,
                 help="show program's version number and exit"):
        super().__init__(option_strings=option_strings, dest=dest, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"{parser.prog} {_pkg_version()}")
        parser.exit()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="paladin",
        description="Credential broker for AI agents — the agent never sees the value.",
    )
    p.add_argument("--version", action=_LazyVersionAction)
    p.add_argument("--vault", type=Path, default=None,
                   help="vault path (default: ~/.paladin/vault.paladin, or $PALADIN_HOME)")
    # Not required: running `paladin` with no subcommand is valid and launches
    # the interactive menu (for a human) or prints help (for a script/pipe),
    # handled in main(). A required subparser would reject bare `paladin` with
    # an argparse error before that handling could run.
    sub = p.add_subparsers(dest="command", required=False)

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

    sp = sub.add_parser(
        "import",
        help="bulk-import credentials: .env files, Bitwarden, 1Password, or discover",
        description=(
            "Import credentials in bulk. Sources: `env <path>` (a .env file or a "
            "directory of them), `csv <file>` / `json <file>` (a password-manager "
            "export or a secrets dump — offline, no CLI needed), `bitwarden` / "
            "`1password` (via their CLIs, which must be installed and unlocked), "
            "or `discover` (report-only: shows where credentials live and the "
            "exact command to import each source). Already-vaulted names are "
            "skipped unless --overwrite. Values are never printed."
        ))
    sp.add_argument("source",
                    choices=["env", "csv", "json", "bitwarden", "1password", "discover"],
                    help="where to import from")
    sp.add_argument("path", nargs="?", default=None,
                    help="for `env`/`csv`/`json`: the file (or directory, for env) to read")
    sp.add_argument("--recursive", action="store_true",
                    help="env: also scan subdirectories (skips node_modules/.git/...)")
    sp.add_argument("--pattern", default=".env*",
                    help="env: filename pattern to match (default: .env*)")
    sp.add_argument("--search", default=None,
                    help="bitwarden/1password: only items matching this term")
    sp.add_argument("--folder", default=None,
                    help="bitwarden: only items in this folder")
    sp.add_argument("--from-vault", default=None, metavar="NAME",
                    help="1password: only items in this 1Password vault")
    sp.add_argument("--profile", default="default",
                    help="paladin profile to import into (default: default)")
    sp.add_argument("--dry-run", action="store_true",
                    help="show what would be imported without adding anything")
    sp.add_argument("--overwrite", action="store_true",
                    help="replace entries that already exist (default: skip them)")
    sp.add_argument("--json", action="store_true",
                    help="machine-readable report (names/kinds only, never values)")
    sp.set_defaults(fn=cmd_import)

    sp = sub.add_parser("grant", help="allow a requester to resolve matching refs")
    sp.add_argument("pattern", help="ref name or glob, e.g. 'stripe/*'")
    sp.add_argument("--to", required=True,
                    help="exact requester id, e.g. skill:stripe-spend")
    sp.add_argument("--max-band", default="L2", choices=["L0", "L1", "L2", "L3", "L4"])
    sp.add_argument("--ttl", type=float, default=None, help="grant lifetime in seconds")
    sp.add_argument("--note", default=None)
    sp.add_argument("--host", action="append",
                    help="restrict sandboxed egress to this hostname (repeatable)")
    sp.add_argument("--method", action="append",
                    help="restrict sandboxed egress to this HTTP method (repeatable)")
    sp.add_argument("--path-prefix", default=None,
                    help="restrict sandboxed egress to URLs whose path starts with this")
    sp.set_defaults(fn=cmd_grant)

    sp = sub.add_parser("revoke", help="remove grants for (pattern, requester)")
    sp.add_argument("pattern")
    sp.add_argument("--to", required=True)
    sp.set_defaults(fn=cmd_revoke)

    sp = sub.add_parser("grants", help="list active grants")
    sp.set_defaults(fn=cmd_grants)

    sp = sub.add_parser("exec", help="run a command with secrets injected into its env")
    sp.add_argument("--with", dest="with_refs", action="append", metavar="NAME[=ENV_VAR]",
                    help="inject one secret (repeatable). With --sandbox, names a ref "
                         "the child may use via the egress gateway (never injected)")
    sp.add_argument("--profile", default=None, help="inject a whole profile")
    sp.add_argument("--sandbox", action="store_true",
                    help="network-isolate the child: no secret in its env, reaches "
                         "the outside only through the Paladin egress gateway")
    sp.add_argument("--as", dest="as_requester", default=CLI_REQUESTER,
                    help="requester identity for grant checks (default user:cli)")
    sp.add_argument("--band", default="L0", choices=["L0", "L1", "L2", "L3", "L4"],
                    help="authority band for sandboxed egress resolution")
    sp.add_argument("--allow-unsandboxed", action="store_true",
                    help="with --sandbox: if isolation is unavailable, run anyway "
                         "(secrets still stay out of the child env) instead of failing")
    sp.add_argument("cmd", nargs=argparse.REMAINDER,
                    help="command to run (prefix with --)")
    sp.set_defaults(fn=cmd_exec)

    sp = sub.add_parser("audit", help="inspect or verify the audit chain")
    sp.add_argument("action", nargs="?", default="tail", choices=["tail", "verify"])
    sp.add_argument("--tail", type=int, default=20)
    sp.set_defaults(fn=cmd_audit)

    sp = sub.add_parser("rotate-master", help="re-encrypt the vault under a new passphrase")
    sp.set_defaults(fn=cmd_rotate_master)

    sp = sub.add_parser(
        "backup",
        help="save an encrypted backup of the vault + audit trail (one file)")
    sp.add_argument("dest", nargs="?", default=None,
                    help="destination file or directory "
                         "(default: ~/paladin-backups/paladin-backup-<time>.zip)")
    sp.add_argument("--force", action="store_true",
                    help="overwrite the destination if it exists")
    sp.set_defaults(fn=cmd_backup)

    sp = sub.add_parser(
        "restore",
        help="restore from a backup (verified to open BEFORE anything is replaced)")
    sp.add_argument("source",
                    help="a backup .zip from `paladin backup`, or a bare vault file")
    sp.add_argument("--force", action="store_true",
                    help="replace an existing vault (it is saved to "
                         "<vault>.pre-restore first — nothing is ever lost)")
    sp.set_defaults(fn=cmd_restore)
    sp = sub.add_parser("doctor", help="report whether sandboxed egress is available here")
    sp.set_defaults(fn=cmd_doctor)

    sp = sub.add_parser("menu", help="interactive menu — no syntax to memorize")
    sp.set_defaults(fn=cmd_menu)

    sp = sub.add_parser(
        "git-setup",
        help="configure git to pull a host's token from the vault (no more tokens in URLs)")
    sp.add_argument("host", help="the git host, e.g. github.com")
    sp.add_argument("ref", help="the vault entry holding the token, e.g. github_token")
    sp.add_argument("--local", action="store_true",
                    help="configure the current repo only (default: --global)")
    sp.set_defaults(fn=cmd_git_setup)

    sp = sub.add_parser(
        "git-credential",
        help="git credential helper (git calls this; you use `git-setup`)")
    sp.add_argument("action", choices=["get", "store", "erase"])
    sp.add_argument("--ref", required=True, help="vault entry holding the token")
    sp.set_defaults(fn=cmd_git_credential)

    return p


def main_import(argv=None) -> int:
    """Entry point for the `paladin-import` console script — sugar for
    `paladin import …` so the one-command bulk-import story reads naturally:

        paladin-import discover
        paladin-import env ~/projects --recursive
        paladin-import bitwarden --search "api key"
    """
    if argv is None:
        argv = sys.argv[1:]
    return main(["import", *argv])


def cmd_menu(args) -> int:
    from paladin.menu import run_menu
    return run_menu()


def cmd_git_credential(args) -> int:
    from paladin import git_credential
    return git_credential.run(args.action, args.ref, vault_path=args.vault)


def cmd_git_setup(args) -> int:
    from paladin import git_credential
    return git_credential.setup(args.host, args.ref,
                                scope="local" if args.local else "global")


def main(argv=None) -> int:
    try:
        from paladin._encoding import force_utf8_io
        force_utf8_io()
    except Exception:
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    # No subcommand: launch the interactive menu if a human is at the terminal,
    # otherwise print help (so pipes/scripts/CI still get predictable output
    # instead of a menu that would hang waiting on stdin).
    if getattr(args, "fn", None) is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return cmd_menu(args)
        parser.print_help()
        return 0
    if getattr(args, "cmd", None) and args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]
    try:
        return args.fn(args)
    except PaladinError as e:
        print(f"paladin: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
