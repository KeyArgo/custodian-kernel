"""Shared action-to-gate classification for every harness adapter."""
from __future__ import annotations

import os
import re
from typing import Any

from custodian.adapters.builtin._paths import resolve as canonicalize

_PACKAGE_RE = re.compile(
    r"(?:^|[;&|\n]\s*)(?:python(?:3(?:\.\d+)?)?\s+-m\s+)?pip\s+install\b"
    r"|(?:^|[;&|\n]\s*)(?:npm|pnpm|yarn|apt|apt-get|dnf|zypper|brew)\s+"
    r"(?:install|add)\b", re.I,
)
_GIT_WRITE_RE = re.compile(
    r"\bgit\s+(?:push|commit|tag|merge|rebase|cherry-pick)\b"
    r"|\bgh\s+(?:pr\s+(?:create|merge)|release\s+create|repo\s+create)\b", re.I,
)


def _outside(path: str, workspace: str) -> bool:
    if not path:
        return False
    try:
        root = canonicalize(workspace)
        return path != root and not path.startswith(root + os.sep)
    except (OSError, RuntimeError, ValueError):
        return True


def gates_for(
    *, tool: str, kind: str, arguments: dict[str, Any],
    workspace: str, paths: list[str],
) -> list[str]:
    """Return the ordered, de-duplicated kernel gate set for an action."""
    gates: list[str] = []
    if kind == "read":
        gates.append("filesystem_read")
    if kind == "write":
        gates.append("filesystem_write")
    if any(_outside(path, workspace) for path in paths):
        gates.append("outside_workspace")
    normalized = tool.strip().lower()
    raw = arguments.get("command", arguments.get("cmd", ""))
    command = " ".join(map(str, raw)) if isinstance(raw, (list, tuple)) else str(raw)
    if normalized in {"shell", "bash", "terminal", "shell-exec", "exec", "exec_command"}:
        gates.append("shell")
    gates.extend({
        "network": ["network"],
        "credential": ["credentials"],
        "destructive": ["destructive"],
        "production": ["production"],
        "money": ["money"],
        "governance": ["governance"],
    }.get(kind, []))
    if _PACKAGE_RE.search(command):
        gates.append("package_install")
    if _GIT_WRITE_RE.search(command) or normalized == "git-push":
        gates.append("git_write")
    return list(dict.fromkeys(gates))
