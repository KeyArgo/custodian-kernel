"""Shared path-resolution helpers for the filesystem guard adapters.

Both ScopeFence (allowlist / task confinement) and PathFence (denylist /
forbidden paths) need to turn a raw path argument — possibly relative,
possibly full of ``..`` traversal — into a single normalized absolute
form before matching it against prefixes or globs. Doing that in one
place means a traversal-escape fix (``/tmp/task/../../etc/passwd`` must
not slip past a ``/tmp/task`` prefix) is fixed for every guard at once,
not re-derived per adapter.
"""
from __future__ import annotations

import os
import re
from typing import Any, Mapping

from custodian.adapters.base import _strings_of

# Argument keys that carry a filesystem path across the tools we govern
# (Hermes: read_file/write_file use "path"/"file_path"; generic tools use
# dest/src/output/input). Matched case-insensitively as a substring.
PATH_ARG_HINT = re.compile(r"(path|file|dir|dest|src|output|input)", re.I)


def looks_like_path(value: str) -> bool:
    """True if a string value is plausibly a filesystem path worth checking.

    Deliberately inclusive: a bare filename with no separator ("secrets.db")
    still counts, because a fail-closed fence must not have an input shape
    that silently skips the check. The only things excluded are values that
    can't be paths at all (empty, or obviously a URL)."""
    if not value:
        return False
    # "warden://" is the pre-rename ref scheme; refs minted before the rename
    # are still in circulation and are no more a filesystem path than the
    # current ones.
    if value.startswith(("http://", "https://", "paladin://", "warden://")):
        return False
    return True


def path_values(args: Mapping[str, Any]) -> list[str]:
    """Every path-shaped string in ``args``, including ones nested in
    containers.

    Guards that walk ``args.items()`` and ``continue`` on
    ``not isinstance(value, str)`` never inspect ``{"path": ["/etc/passwd"]}``
    or ``{"path": {"value": "..."}}`` — ordinary JSON tool-call shapes. That
    contradicts ``looks_like_path``'s own promise above: a fail-closed fence
    must not have an input shape that silently skips the check. The recursion
    mirrors ``base._strings_of``, which every text-scanning guard already
    relies on, so a container arg is no longer invisible to only the path
    guards.
    """
    out: list[str] = []
    for key, value in args.items():
        if not PATH_ARG_HINT.search(key):
            continue
        out.extend(s for s in _strings_of(value) if looks_like_path(s))
    return out


def resolve(value: str, base: str = "/") -> str:
    """Normalize a path argument to an absolute, traversal-collapsed,
    symlink-resolved form.

    Relative paths are resolved against ``base`` (default ``/`` — we care
    about containment relative to configured absolute prefixes, not the
    process CWD). ``~`` is expanded. ``..`` segments are collapsed, and any
    symlink in the path is followed to its real target — so a symlink
    planted inside an otherwise-safe directory that points at a forbidden
    location (``ln -s ~/.ssh /tmp/work/evil && cat /tmp/work/evil/id_rsa``)
    resolves to the forbidden location itself, not the symlink's own path
    string (found live in review: a prior normpath-only version let exactly
    this through). ``realpath`` degrades to normpath-only behavior for a
    path that doesn't exist on disk yet — nothing to follow — so this is a
    pure strengthening with no new failure mode for ordinary paths."""
    # Tool calls may carry paths authored for a remote/other platform.  On
    # POSIX, backslash is an ordinary character, so a native Windows-shaped
    # path (or a POSIX absolute path rendered with backslashes) previously
    # never matched a protected POSIX prefix.  Normalise the alternate
    # separator before applying the host's path rules.  Windows already
    # accepts forward slashes, so the inverse conversion is unnecessary.
    if os.sep == "\\":
        portable = value
    else:
        portable = value.replace("\\", "/")
    expanded = os.path.expanduser(portable)
    if not os.path.isabs(expanded):
        expanded = os.path.join(base, expanded)
    return os.path.realpath(expanded)


def under_prefix(resolved: str, prefixes: list[str]) -> bool:
    """True if ``resolved`` is exactly one of ``prefixes`` or nested under
    one (segment-aware, so ``/tmp/taskfoo`` is NOT under ``/tmp/task``)."""
    return any(resolved == p or resolved.startswith(p + os.sep) for p in prefixes)
