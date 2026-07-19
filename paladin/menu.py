"""Interactive menu for paladin — a friendly front door so nobody has to
memorize ``paladin exec --with name=ENV -- cmd`` syntax.

Design: the menu never re-implements a command. It asks plain-language
questions, assembles the same argv the CLI would take, and hands it to
``paladin.cli.main``. So every guarantee the CLI makes (values are prompted
via getpass and never echoed, every change is audited, errors are clean) holds
here for free, and there is exactly one code path per action.

Launched by ``paladin menu``, or by running ``paladin`` with no arguments in an
interactive terminal.
"""
from __future__ import annotations

import sys


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise _Back()
    return val or default


def _choose(title: str, options: list[tuple[str, str]]) -> str | None:
    """Show a numbered menu; return the selected key, or None to go back."""
    print(f"\n{title}")
    for i, (_key, label) in enumerate(options, 1):
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


class _Back(Exception):
    """Raised by a prompt to bounce back to the main menu."""


def _run(argv: list[str]) -> None:
    """Delegate to the real CLI and report the outcome plainly."""
    from paladin.cli import main
    try:
        rc = main(argv)
    except SystemExit as e:  # argparse errors on a bad assembled argv
        rc = e.code if isinstance(e.code, int) else 1
    if rc == 0:
        print("  ✓ done")
    else:
        print("  (command reported an issue — see the message above)")


# -- individual actions -------------------------------------------------------

def _act_list() -> None:
    _run(["list"])


def _act_show() -> None:
    name = _prompt("secret name to inspect")
    if name:
        _run(["show", name])


def _act_add() -> None:
    name = _prompt("name for the new secret (e.g. stripe_key)")
    if not name:
        return
    kind = _prompt("kind (secret / token / password)", "secret")
    env = _prompt("environment variable name to expose it as (optional)")
    argv = ["add", name, "--kind", kind]
    if env:
        argv += ["--env-var", env]
    print("  (you'll be prompted for the value — it is never shown)")
    _run(argv)


def _act_delete() -> None:
    name = _prompt("secret name to delete")
    if name and _prompt(f"type '{name}' again to confirm") == name:
        _run(["rm", name])
    elif name:
        print("  (name did not match — nothing deleted)")


def _act_import() -> None:
    src = _choose("Import from where?", [
        ("discover", "Discover — just show me where credentials live"),
        ("env", ".env file (or a folder of them)"),
        ("csv", "CSV export (Chrome/Bitwarden/LastPass/1Password/KeePass)"),
        ("json", "JSON secrets dump"),
        ("bitwarden", "Bitwarden (needs the `bw` CLI, unlocked)"),
        ("1password", "1Password (needs the `op` CLI, signed in)"),
    ])
    if src is None:
        return
    argv = ["import", src]
    if src in ("env", "csv", "json"):
        path = _prompt(f"path to the {src} file" + (" or folder" if src == "env" else ""))
        if not path:
            return
        argv.append(path)
    if _prompt("preview only, without saving? (y/N)", "n").lower().startswith("y"):
        argv.append("--dry-run")
    _run(argv)


def _act_run_with_secret() -> None:
    print("\nRun a command with a secret injected into its environment.")
    print("The child process sees the value; you never do, and it never lands on disk.")
    name = _prompt("secret name to inject")
    if not name:
        return
    env = _prompt("environment variable name the command expects", name.upper())
    cmd = _prompt("command to run (e.g. python bill.py)")
    if not cmd:
        return
    # posix=True so surrounding quotes are stripped (python -c "code" ->
    # ['python','-c','code']); subprocess re-quotes correctly per platform.
    # The trade-off is backslashes are escapes here, so a Windows path is best
    # given with forward slashes (Python accepts them) or via `paladin exec`.
    import shlex
    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError as e:
        print(f"  (could not parse that command: {e})")
        return
    if not parts:
        return
    _run(["exec", "--with", f"{name}={env}", "--", *parts])


def _act_backup() -> None:
    dest = _prompt("backup destination (blank = ~/paladin-backups/…)")
    _run(["backup", dest] if dest else ["backup"])


def _act_restore() -> None:
    src = _prompt("backup file to restore from")
    if src:
        _run(["restore", src, "--force"])


def _act_grants() -> None:
    action = _choose("Access grants", [
        ("grants", "List current grants"),
        ("grant", "Grant a requester access to a secret"),
        ("revoke", "Revoke a requester's access"),
    ])
    if action == "grants":
        _run(["grants"])
    elif action == "grant":
        pattern = _prompt("secret name or glob (e.g. stripe*)")
        who = _prompt("requester id (e.g. skill:stripe-spend)")
        if pattern and who:
            _run(["grant", pattern, "--to", who])
    elif action == "revoke":
        pattern = _prompt("secret name or glob")
        who = _prompt("requester id")
        if pattern and who:
            _run(["revoke", pattern, "--to", who])


def _act_audit() -> None:
    if _prompt("verify the chain's integrity? (Y/n)", "y").lower().startswith("y"):
        _run(["audit", "verify"])
    else:
        _run(["audit"])


def _act_doctor() -> None:
    _run(["doctor"])


_ACTIONS = [
    ("list", "List my secrets (names only)"),
    ("add", "Add a secret"),
    ("run", "Run a command with a secret injected"),
    ("import", "Import credentials in bulk"),
    ("show", "Show one secret's details (never the value)"),
    ("delete", "Delete a secret"),
    ("grants", "Manage who can use which secret"),
    ("backup", "Back up the vault (encrypted, one file)"),
    ("restore", "Restore from a backup"),
    ("audit", "Inspect / verify the audit log"),
    ("doctor", "Check this environment (sandbox, etc.)"),
]

_DISPATCH = {
    "list": _act_list, "add": _act_add, "run": _act_run_with_secret,
    "import": _act_import, "show": _act_show, "delete": _act_delete,
    "grants": _act_grants, "backup": _act_backup, "restore": _act_restore,
    "audit": _act_audit, "doctor": _act_doctor,
}


def run_menu() -> int:
    print("=" * 56)
    print("  Paladin — your credential vault")
    print("  (the agent never sees the values; you're the human)")
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
