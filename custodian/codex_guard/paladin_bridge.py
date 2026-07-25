"""Paladin integration for Custodian Codex Guard.

Paladin is the brand-neutral credential broker. Per the enforced package
boundary (``tests/test_architecture_boundaries.py``) nothing under
``custodian/`` -- codex-guard included -- may *import* ``paladin``; the kernel
and its adapters stay brand-neutral. So this bridge reaches Paladin exactly the
way the guard reaches ``git`` or ``codex``: as an **external tool** (the
``paladin`` CLI on PATH) and as a **file on disk** (the encrypted vault),
never as a Python dependency. The one piece of shared knowledge --- the
``paladin://`` ref syntax --- is re-implemented here as a small regex, the same
way ``custodian/adapters/builtin/secret_leak_guard.py`` already does, rather
than imported.

Paladin is entirely **optional**: every function degrades gracefully when the
CLI is absent, no vault is configured, or the vault is locked. codex-guard is
fully functional without it -- credential actions simply escalate to a human
instead of resolving from a vault.

Two real mechanisms connect Codex to Paladin:

1. **Git credential helper** -- transparent secret delivery. ``paladin
   git-setup <host> <ref>`` wires git so any ``git push`` / ``git fetch`` Codex
   runs resolves the token from the encrypted vault at the moment git asks. The
   token never lands in git config, a remote URL, a command line, or Codex's
   context. This *is* the "Codex doesn't know the password, so it checks Paladin
   first" path, fully transparent to the model.

2. **Credential-action guidance** -- policy. When the guard escalates a
   credential-class action (or any action that already carries a ``paladin://``
   ref) and a vault is configured, the escalation reason steers the
   model/approver to the vault egress path instead of a raw secret. Inlining a
   raw secret is already *denied* upstream by ``SecretLeakGuard``; this adds the
   positive "here is the vault path" half.

The guard **never unlocks the vault on the hot path**: answering "is a vault
configured?" is a pure filesystem check (does the vault file exist?), never the
passphrase. Actual resolution happens at egress *inside Paladin* (the git
helper, or an explicit ``paladin exec``), never inside a PreToolUse hook that
fires on every tool call.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

# Paladin's vault-location contract, replicated (not imported) so we can answer
# "is a vault configured?" without a paladin dependency. Kept in sync with
# paladin/vault.py: PALADIN_HOME (or legacy WARDEN_HOME) wins; otherwise
# ~/.paladin, falling back to a pre-rename ~/.warden if only that exists.
_HOME_ENV = "PALADIN_HOME"
_LEGACY_HOME_ENV = "WARDEN_HOME"
_VAULT_FILENAME = "vault.paladin"
_LEGACY_VAULT_FILENAME = "vault.warden"

# The paladin:// (and legacy warden://) ref syntax, re-implemented locally to
# keep custodian/ free of a paladin import -- mirrors secret_leak_guard.py's
# own copy. A ref is value-free: safe to read, log, and surface to a model.
_REF_RE = re.compile(r"(?:paladin|warden)://([a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127})")


def _default_vault_dir() -> Path:
    """The vault home Paladin would use, resolved at call time.

    Filesystem/env only -- never opens or decrypts anything.
    """
    explicit = os.environ.get(_HOME_ENV)
    if explicit is None:
        explicit = os.environ.get(_LEGACY_HOME_ENV)
    # Truthy, not `is not None`: an empty PALADIN_HOME is not a location (it would
    # resolve to the cwd), so fall through to the default -- matching paladin.
    if explicit:
        return Path(explicit).expanduser()
    current = Path("~/.paladin").expanduser()
    if not current.exists() and Path("~/.warden").expanduser().exists():
        return Path("~/.warden").expanduser()
    return current


def paladin_available() -> bool:
    """True if the ``paladin`` CLI is on PATH.

    We treat Paladin as an external tool, so availability means the command
    exists -- not that a Python package can be imported (which the package
    boundary forbids us from checking anyway).
    """
    return shutil.which("paladin") is not None


def vault_path() -> Path | None:
    """The vault file Paladin would use, without opening (decrypting) it.

    Honors ``PALADIN_HOME``; never needs the passphrase, so it is safe on a
    hot path. Returns the current-scheme path, or the legacy path if only that
    exists.
    """
    base = _default_vault_dir()
    current = base / _VAULT_FILENAME
    if not current.exists() and (base / _LEGACY_VAULT_FILENAME).exists():
        return base / _LEGACY_VAULT_FILENAME
    return current


def vault_configured() -> bool:
    """True if a Paladin vault file exists (regardless of whether it's locked)."""
    path = vault_path()
    return bool(path and path.exists())


def _iter_strings(value: Any):
    """Yield every string anywhere in a nested arguments structure.

    Mirrors the guard's own ``_strings`` so ref discovery is exactly as thorough
    as the risk classifier: a ``paladin://`` ref nested in a list or dict is
    found here too, not just a top-level string value.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_strings(nested)


def refs_in_arguments(arguments: dict[str, Any] | None) -> list[str]:
    """Ref names (``paladin://<name>`` -> ``<name>``) appearing in arg values.

    Value-free: a ref is a zero-value pointer, safe to read and log. Returns a
    de-duplicated, order-preserving list. Empty when no ref is present. Recurses
    into nested lists/dicts so it never misses a ref the classifier would see.
    """
    if not arguments:
        return []
    seen: dict[str, None] = {}
    for value in _iter_strings(arguments):
        for match in _REF_RE.finditer(value):
            seen.setdefault(match.group(1), None)
    return list(seen)


# credential.https://<host>.helper = !paladin git-credential --ref <ref>
_HELPER_KEY_RE = re.compile(r"^credential\.https://(?P<host>[^.].*?)\.helper$")
_HELPER_REF_RE = re.compile(r"paladin git-credential --ref (?P<ref>\S+)")


def git_helpers() -> list[tuple[str, str]]:
    """Return ``[(host, ref)]`` for every git remote wired to the Paladin helper.

    Reads ``git config`` (global scope) only -- no vault access. Returns an
    empty list if git is absent or no Paladin helper is configured.
    """
    try:
        proc = subprocess.run(
            ["git", "config", "--global", "--get-regexp", r"^credential\..*\.helper$"],
            text=True, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode not in (0, 1):  # 1 == no matching keys, which is fine
        return []
    helpers: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or " " not in line:
            continue
        key, value = line.split(" ", 1)
        key_match = _HELPER_KEY_RE.match(key)
        ref_match = _HELPER_REF_RE.search(value)
        if key_match and ref_match:
            helpers.append((key_match.group("host"), ref_match.group("ref")))
    return helpers


def credential_guidance(arguments: dict[str, Any] | None) -> str:
    """Paladin-aware suffix for a credential-class escalation reason.

    Returns ``""`` (no change) when no vault is configured -- the action then
    escalates to a human exactly as before. When a vault *is* configured, the
    returned text points at the safe egress path so the model doesn't prompt for
    or inline a raw secret; the human approver sees it too.
    """
    if not vault_configured():
        return ""
    refs = refs_in_arguments(arguments)
    if refs:
        named = ", ".join(f"paladin://{name}" for name in refs)
        return (
            f" Paladin is configured and this action references {named}; resolve "
            f"it at egress (the git credential helper for git ops, or "
            f"`paladin exec --with VAR=paladin://<ref> -- <cmd>`) -- never inline "
            f"or print the value."
        )
    return (
        " Paladin is configured: resolve any needed secret through the vault "
        "(`paladin add <name>`, then reference `paladin://<name>` and run it via "
        "the git helper or `paladin exec`) -- do not prompt for or inline a raw "
        "secret that skips the vault."
    )


def wire_git_helper(host: str, ref: str) -> tuple[bool, str]:
    """Wire git -> Paladin for one host/ref by invoking the ``paladin`` CLI.

    Shells out to ``paladin git-setup <host> <ref>`` (a process boundary, not an
    import), which validates the ref, grants the git helper access to just that
    ref, and configures ``credential.https://<host>.helper``. Returns
    ``(ok, message)``; never raises.
    """
    if not paladin_available():
        return False, "paladin CLI not on PATH"
    try:
        proc = subprocess.run(
            ["paladin", "git-setup", host, ref],
            text=True, capture_output=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"paladin git-setup failed ({type(exc).__name__}: {exc})"
    if proc.returncode == 0:
        return True, (proc.stdout.strip()
                      or f"git will resolve credentials for {host} from paladin://{ref}")
    detail = (proc.stderr or proc.stdout).strip()
    return False, f"paladin git-setup failed: {detail or f'exit {proc.returncode}'}"


def status_summary() -> dict[str, Any]:
    """Structured Paladin status for ``doctor`` -- all value-free, no unlock."""
    path = vault_path()
    return {
        "available": paladin_available(),
        "vault_path": str(path) if path else None,
        "vault_configured": vault_configured(),
        "git_helpers": git_helpers(),
    }
