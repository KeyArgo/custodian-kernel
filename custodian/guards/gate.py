"""Guard enablement gate — the single source of truth for which harness
guards are active.

Every surface (the ``custodian guards`` CLI, ``install-custodian.py``,
the Hermes plugin, future dotfiles) reads and writes this ONE state file,
so "enabled" can never disagree between Hermes and the terminal.

Guards are dormant by default: installing custodian-kernel activates
nothing. ``custodian guards enable <name>`` is the only path that flips a
guard on, and ``custodian guards status`` is the auditable record.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

GUARD_NAMES = ("codex", "claude", "hermes")
_STATE_FILENAME = "guards.json"


def default_state_dir() -> str:
    return os.environ.get("CUSTODIAN_STATE_DIR", str(Path.home() / ".custodian"))


def state_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / _STATE_FILENAME


def load_state(state_dir: str | Path) -> dict:
    p = state_path(state_dir)
    if not p.is_file():
        return {"version": 1, "guards": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"version": 1, "guards": {}}
    data.setdefault("version", 1)
    data.setdefault("guards", {})
    return data


def _write_state(state_dir: str | Path, data: dict) -> None:
    p = state_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def _validate(name: str) -> None:
    if name not in GUARD_NAMES:
        raise ValueError(
            f"unknown guard {name!r}; choices: {', '.join(GUARD_NAMES)}"
        )


def is_enabled(state_dir: str | Path, name: str) -> bool:
    return bool(load_state(state_dir)["guards"].get(name, {}).get("enabled", False))


def enable(state_dir: str | Path, name: str) -> bool:
    """Return True if the guard was turned on, False if it already was."""
    _validate(name)
    data = load_state(state_dir)
    rec = data["guards"].setdefault(name, {})
    if rec.get("enabled"):
        return False
    rec["enabled"] = True
    rec["updated_at"] = time.time()
    _write_state(state_dir, data)
    return True


def disable(state_dir: str | Path, name: str) -> bool:
    """Return True if the guard was turned off, False if it was already off."""
    _validate(name)
    data = load_state(state_dir)
    rec = data["guards"].get(name)
    if not rec or not rec.get("enabled"):
        return False
    rec["enabled"] = False
    rec["updated_at"] = time.time()
    _write_state(state_dir, data)
    return True


def status_report(state_dir: str | Path) -> list[dict]:
    state = load_state(state_dir)
    return [
        {
            "name": n,
            "enabled": bool(state["guards"].get(n, {}).get("enabled", False)),
            "updated_at": state["guards"].get(n, {}).get("updated_at"),
        }
        for n in GUARD_NAMES
    ]
