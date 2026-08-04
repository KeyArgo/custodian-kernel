"""ANSI operator dashboard for Paladin — guard, sandbox, grants, backups.

One-shot render: call :func:`render` with a Broker and a backups directory
(or None) and it prints a color-coded terminal dashboard.  No interactive
loop, no curses — just a clean snapshot the operator can re-run any time.
"""
from __future__ import annotations

import os
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from paladin.sandbox import bwrap_path, sandbox_available, unsafe_acknowledged

# -- ANSI helpers --------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"

OK = f"{_GREEN}OK  ✓{_RESET}"
WARN = f"{_YELLOW}WARN !{_RESET}"
FAIL = f"{_RED}FAIL ✗{_RESET}"
NA = f"{_DIM}n/a{_RESET}"


def _label(text: str, width: int = 22) -> str:
    return f"{_BOLD}{text:<{width}}{_RESET}"


def _kv(key: str, value: str, indent: int = 2) -> str:
    return f"{' ' * indent}{_label(key)}{value}"


def _box(title: str, body: str) -> str:
    width = 68
    top = f"┌── {_BOLD}{title}{_RESET} {'─' * (width - len(title) - 6)}┐"
    bottom = f"└{'─' * (width - 2)}┘"
    return f"\n{top}\n{body}\n{bottom}"


def _divider() -> str:
    return f"  {_DIM}{'·' * 62}{_RESET}"


def _age(dt: Optional[float]) -> str:
    if dt is None:
        return "never"
    delta = datetime.now(timezone.utc).timestamp() - dt
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta / 60)}m ago"
    if delta < 86400:
        return f"{int(delta / 3600)}h ago"
    return f"{int(delta / 86400)}d ago"


def _check(val: bool) -> str:
    return OK if val else FAIL


# -- Sections ------------------------------------------------------------------


def _guard_section(broker) -> str:
    status = broker.guard.status()
    lines = [
        _kv("Guard Status:", OK if status.healthy else FAIL),
        _kv("Audit Records:", f"{status.valid_records:,} verified"),
        _kv("Audit SHA-256:", status.audit_sha256[:16] + "..." if status.audit_sha256 else "(none)"),
    ]
    if not status.healthy:
        lines.append(_kv("Problem:", f"{_RED}{status.problem}{_RESET}"))
    return _box("Guard", "\n".join(lines))


def _sandbox_section() -> str:
    bw = bwrap_path()
    available = sandbox_available()
    acked = unsafe_acknowledged()

    lines = [
        _kv("bwrap:", bw or f"{_RED}(not found){_RESET}"),
        _kv("Sandbox Available:", _check(available)),
        _kv("Unsafe Ack:", OK if acked else f"{_YELLOW}not set{_RESET}"),
    ]
    if not acked:
        lines.append(
            _kv("", f"{_YELLOW}set PALADIN_UNSAFE_ACKNOWLEDGED=1 to suppress banner{_RESET}")
        )
    return _box("Sandbox", "\n".join(lines))


def _grants_section(broker) -> str:
    grants = broker.grants.list()
    if not grants:
        lines = [f"  {_DIM}(no grants — deny-by-default for all requesters){_RESET}"]
    else:
        lines = []
        for g in grants[:20]:  # cap at 20 for display
            ttl = _age(g.expires_at) if g.expires_at else "never"
            scope = ""
            if g.allowed_hosts or g.methods or g.path_prefix:
                hosts = ",".join(g.allowed_hosts) if g.allowed_hosts else "*"
                meths = ",".join(g.methods) if g.methods else "*"
                scope = f" [{hosts}/{meths}/{g.path_prefix or '*'}]"
            lines.append(
                f"  {g.ref_pattern:<22} → {g.requester:<22} ≤{g.max_band}  {_DIM}{ttl}{_RESET}{scope}"
            )
        if len(grants) > 20:
            lines.append(f"  {_DIM}... and {len(grants) - 20} more{_RESET}")
    return _box("Grants", "\n".join(lines))


def _backups_section(broker, backups_dir: Optional[Path]) -> str:
    status = broker.guard.status()
    current_hash = status.audit_sha256

    if not backups_dir or not Path(backups_dir).expanduser().is_dir():
        lines = [f"  {_DIM}(no backup directory specified — pass --backups DIR){_RESET}"]
    else:
        passphrase = os.environ.get("PALADIN_PASSPHRASE")
        try:
            matches = broker.guard.backup_audit_hashes(
                backups_dir, passphrase=passphrase,
            )
        except Exception:
            matches = []
        if not matches:
            lines = [f"  {_DIM}(no backup archives found in {backups_dir}){_RESET}"]
        else:
            lines = []
            for name, digest in matches:
                if digest.startswith("(locked"):
                    state = f"{_YELLOW}{digest}{_RESET}"
                elif digest == current_hash and current_hash:
                    state = f"{_GREEN}matches current{_RESET}"
                elif current_hash:
                    state = f"{_YELLOW}different{_RESET}"
                else:
                    state = f"{_DIM}no current audit to compare{_RESET}"
                lines.append(f"  {name:<52} {state}")
    return _box("Backups", "\n".join(lines))


def _vault_section(broker) -> str:
    vault = broker.vault
    path = vault.path
    entries = len(vault._entries)
    profiles = len({e.profile for e in vault._entries.values()}) if vault._entries else 0
    grants = len(broker.grants.list())

    lines = [
        _kv("Vault Path:", str(path)),
        _kv("Entries:", f"{entries} ({profiles} profile{'s' if profiles != 1 else ''})"),
        _kv("Grants:", str(grants)),
    ]
    return _box("Vault", "\n".join(lines))


def _deprecation_footer() -> str:
    acked = unsafe_acknowledged()
    if acked:
        return ""
    return textwrap.dedent(f"""
  {_YELLOW}╔══════════════════════════════════════════════════════════════════╗
  ║  Unsandboxed execution is DEPRECATED and will be removed.      ║
  ║  Migrate to `paladin exec --sandbox` for network isolation.    ║
  ║  Set PALADIN_UNSAFE_ACKNOWLEDGED=1 to acknowledge & suppress.   ║
  ╚══════════════════════════════════════════════════════════════════╝{_RESET}
    """).rstrip()


# -- Main render ---------------------------------------------------------------


def render(broker, backups_dir: Optional[Path] = None) -> str:
    """Return the full ANSI dashboard as a string (print-ready)."""
    sections = [
        _guard_section(broker),
        _sandbox_section(),
        _vault_section(broker),
        _grants_section(broker),
        _backups_section(broker, backups_dir),
    ]
    out = "\n".join(sections)
    footer = _deprecation_footer()
    if footer:
        out += "\n" + footer
    return out
