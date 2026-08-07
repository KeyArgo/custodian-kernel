"""Install/verify/remove the Custodian PreToolUse hook in Codex's config.toml.

Enforcement lives in a hook, not the opt-in MCP tool, so this is what makes the
guard mandatory. We manage exactly one delimited block so the edit is idempotent
and never disturbs the operator's other config, and we validate the whole file
parses as TOML both before and after -- refusing to touch a file we can't parse
rather than risk clobbering it (there is no TOML *writer* in the stdlib, only the
``tomllib`` reader, so the block is emitted as text and then re-parsed to prove
it is well formed).

The command is pinned to the exact interpreter that installed it, so a later
PATH change can't silently swap in an ungoverned Python.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tomllib

HOOK_MODULE = "custodian.codex_guard.hook"
HOOK_MARKER = "custodian.codex_guard.hook"  # identifies our command line
BEGIN = "# >>> custodian-codex-guard managed hook (do not edit by hand) >>>"
END = "# <<< custodian-codex-guard managed hook <<<"
# Unanchored regex -> matches every tool name. Reads/writes/tests still resolve
# to the autonomous band (defer, no output), so this governs everything without
# prompting on every call; only consequential or unknown/MCP tools are blocked.
DEFAULT_MATCHER = ".*"


class HookInstallError(RuntimeError):
    """The config file is unparseable or the edit would produce invalid TOML."""


def codex_config_path() -> Path:
    home = os.environ.get("CODEX_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".codex"
    return base / "config.toml"


def managed_dir() -> Path:
    """Directory for Codex's *managed* config layer, resolved per platform so a
    managed install works for every user, not just Linux.

    A managed hook is auto-trusted ("Managed hooks are always on") and runs in
    non-interactive `exec` without a TUI trust prompt; with
    `allow_managed_hooks_only` it also cannot be overridden by user/project/
    session config. Codex reads this from a root/admin-owned system location
    (its own config keys `managed_dir` / `windows_managed_dir`), which is what
    makes it unstrippable by the model or a project config.

    Resolution order:
      1. CUSTODIAN_CODEX_MANAGED_DIR  -- explicit override (tests, MDM, or a
         deliberately operator-owned managed dir on a machine without root).
      2. Windows: %PROGRAMDATA%\\Codex   (all-users, admin-owned by default).
      3. macOS/Linux/other POSIX: /etc/codex  (root-owned).
    """
    override = os.environ.get("CUSTODIAN_CODEX_MANAGED_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "Codex"
    return Path("/etc/codex")


def elevation_hint() -> str:
    """The exact command an operator runs to gain write access to managed_dir."""
    if sys.platform.startswith("win"):
        return "run this in an Administrator terminal"
    return "rerun with sudo"


def install_managed(*, matcher: str = DEFAULT_MATCHER, python: str | None = None,
                    lock: bool = True) -> tuple[Path, Path | None]:
    """Install the guard as an always-on managed hook, and (by default) lock the
    config so only managed hooks run. Returns (managed_config_path, requirements
    _path_or_None). May raise PermissionError if the managed dir is root-owned.
    """
    mdir = managed_dir()
    mdir.mkdir(parents=True, exist_ok=True)
    cfg = mdir / "managed_config.toml"
    existing = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    if existing.strip():
        _validate(existing)
    base = _strip_our_block(existing).rstrip()
    block = _block(matcher, python)
    new_text = (base + "\n\n" + block + "\n") if base else (block + "\n")
    _validate(new_text)
    cfg.write_text(new_text, encoding="utf-8")

    req_path: Path | None = None
    if lock:
        req_path = mdir / "requirements.toml"
        req = req_path.read_text(encoding="utf-8") if req_path.exists() else ""
        if req.strip():
            _validate(req)
        if "allow_managed_hooks_only" not in req:
            req = (req.rstrip() + "\n" if req.strip() else "")
            req += "allow_managed_hooks_only = true\n"
            _validate(req)
            req_path.write_text(req, encoding="utf-8")
    return cfg, req_path


def uninstall_managed(*, remove_lock: bool = True) -> bool:
    """Operator escape hatch: remove the managed hook (and, by default, the
    managed-only lock) so Codex runs normally again if the guard misbehaves.

    Deliberately privileged -- it edits the root/admin-owned managed dir, so only
    someone with that access (never the model or a project config) can disable
    enforcement. Returns True if anything was removed.
    """
    mdir = managed_dir()
    changed = False
    cfg = mdir / "managed_config.toml"
    if cfg.exists():
        text = cfg.read_text(encoding="utf-8")
        if BEGIN in text:
            _validate(text)
            new_text = _strip_our_block(text).rstrip()
            new_text = new_text + "\n" if new_text else ""
            if new_text.strip():
                _validate(new_text)
                cfg.write_text(new_text, encoding="utf-8")
            else:
                cfg.unlink()  # nothing but our block remained
            changed = True
    if remove_lock:
        req = mdir / "requirements.toml"
        if req.exists():
            lines = [ln for ln in req.read_text(encoding="utf-8").splitlines()
                     if "allow_managed_hooks_only" not in ln]
            new_req = "\n".join(lines).strip()
            if new_req:
                req.write_text(new_req + "\n", encoding="utf-8")
            else:
                req.unlink()
            changed = changed or True
    return changed


def managed_status() -> dict:
    cfg = managed_dir() / "managed_config.toml"
    installed = cfg.exists() and BEGIN in cfg.read_text(encoding="utf-8")
    req = managed_dir() / "requirements.toml"
    locked = req.exists() and "allow_managed_hooks_only" in req.read_text(encoding="utf-8")
    return {"installed": bool(installed), "locked": bool(locked), "path": str(cfg)}


def hook_command(python: str | None = None) -> str:
    return f"{python or sys.executable} -m {HOOK_MODULE}"


def _block(matcher: str, python: str | None = None) -> str:
    return "\n".join([
        BEGIN,
        "[[hooks.PreToolUse]]",
        f"matcher = {_toml_str(matcher)}",
        "",
        "[[hooks.PreToolUse.hooks]]",
        'type = "command"',
        f"command = {_toml_str(hook_command(python))}",
        "timeout = 30",
        END,
    ])


def _toml_str(value: str) -> str:
    # Basic TOML string: escape backslash and double-quote. Interpreter/matcher
    # never contain control chars, so this is sufficient and keeps output stable.
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _strip_our_block(text: str) -> str:
    if BEGIN not in text:
        return text
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            skipping = True
            continue
        if line.strip() == END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "\n".join(out)


def _validate(text: str) -> None:
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise HookInstallError(str(exc)) from exc


def install(config_path: Path | None = None, *, matcher: str = DEFAULT_MATCHER,
            python: str | None = None) -> Path:
    """Install (or refresh) the managed hook block. Returns the config path."""
    path = config_path or codex_config_path()
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing.strip():
        _validate(existing)  # refuse to edit a file we can't parse
    base = _strip_our_block(existing).rstrip()
    block = _block(matcher, python)
    new_text = (base + "\n\n" + block + "\n") if base else (block + "\n")
    _validate(new_text)  # prove the result is well-formed before writing
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".custodian.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def uninstall(config_path: Path | None = None) -> bool:
    """Remove the managed hook block. Returns True if something was removed."""
    path = config_path or codex_config_path()
    if not path.exists():
        return False
    existing = path.read_text(encoding="utf-8")
    if BEGIN not in existing:
        return False
    _validate(existing)
    new_text = _strip_our_block(existing).rstrip() + "\n"
    _validate(new_text)
    path.write_text(new_text, encoding="utf-8")
    return True


def status(config_path: Path | None = None, *, python: str | None = None) -> dict:
    """Return {'installed', 'interpreter_current', 'command', 'path'}."""
    path = config_path or codex_config_path()
    result = {"installed": False, "interpreter_current": False,
              "command": None, "path": str(path)}
    if not path.exists():
        return result
    text = path.read_text(encoding="utf-8")
    if BEGIN not in text:
        return result
    result["installed"] = True
    expected = hook_command(python)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("command =") and HOOK_MARKER in stripped:
            result["command"] = stripped.split("=", 1)[1].strip().strip('"')
            result["interpreter_current"] = (result["command"] == expected)
    return result
