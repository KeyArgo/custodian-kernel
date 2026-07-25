"""Self-hardening gate corpus for the guard.

This is the machinery behind "caught once -> permanent gate; it can never
silently return." A *corpus* is an append-only list of concrete adversarial
inputs, each frozen at a **floor verdict** -- the minimum strictness the guard
must apply to it. The standing gate (`tests/test_guard_gate_corpus.py`) replays
the whole corpus on every build and fails if any entry's verdict has grown
*weaker* than its floor.

The ratchet is deliberately **monotonic in the safe direction**: a verdict may
get stricter over time (escalation -> denied is fine) but never weaker
(escalation -> autonomous fails the build). That is what makes a fixed bypass
impossible to silently reopen, while still letting the guard tighten.

What improves itself is *coverage*, not the guard's decision logic. The corpus
grows automatically (from `scripts/harden_guard.py`, which generates adversarial
inputs, freezes the caught ones, and flags the escapes for a human to fix). The
guard's decision code stays human-authored on purpose: a security boundary that
silently rewrote its own logic would be a liability, not a feature.

Kept brand-neutral (no paladin import) like the rest of `custodian/`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .guard import evaluate_action

# Strictness ordering. A gate passes iff the guard's verdict is at least as
# strict as the entry's floor. "approved" only arises from a live operator
# approval, which replay never has, so it does not appear as a floor.
SEVERITY = {
    "autonomous": 0,
    "approved": 1,
    "escalation_required": 2,
    "denied": 3,
}

# Verdicts an entry may be frozen at: only the "caught" ones. Freezing an
# `autonomous` floor would be meaningless (everything satisfies it) and would
# risk freezing a bug as if it were correct behavior.
VALID_FLOORS = ("escalation_required", "denied")

WORKSPACE_KINDS = ("project", "home")


class CorpusError(ValueError):
    """A corpus entry is malformed -- fail loudly, never skip silently."""


def severity(verdict: str) -> int:
    try:
        return SEVERITY[verdict]
    except KeyError as exc:
        raise CorpusError(f"unknown verdict {verdict!r}") from exc


def entry_signature(entry: dict[str, Any]) -> str:
    """A stable de-dup key: two entries with the same input are the same gate,
    regardless of floor (the stricter floor wins when merging)."""
    return json.dumps(
        {
            "tool": entry.get("tool"),
            "action_kind": entry.get("action_kind"),
            "arguments": entry.get("arguments"),
            "workspace": entry.get("workspace"),
        },
        sort_keys=True, separators=(",", ":"),
    )


def validate_entry(entry: dict[str, Any]) -> None:
    if not isinstance(entry, dict):
        raise CorpusError(f"entry is not an object: {entry!r}")
    for key in ("tool", "action_kind", "arguments", "workspace", "floor"):
        if key not in entry:
            raise CorpusError(f"entry missing {key!r}: {entry!r}")
    if not isinstance(entry["tool"], str) or not entry["tool"]:
        raise CorpusError(f"tool must be a non-empty string: {entry!r}")
    if not isinstance(entry["arguments"], dict):
        raise CorpusError(f"arguments must be an object: {entry!r}")
    if entry["workspace"] not in WORKSPACE_KINDS:
        raise CorpusError(f"workspace must be one of {WORKSPACE_KINDS}: {entry!r}")
    if entry["floor"] not in VALID_FLOORS:
        raise CorpusError(f"floor must be one of {VALID_FLOORS}: {entry!r}")


def _workspace_for(kind: str, project_workspace: str) -> str:
    if kind == "home":
        return str(Path.home())
    return project_workspace


def replay_verdict(entry: dict[str, Any], *, project_workspace: str) -> str:
    """Run one corpus entry through the guard's core classifier and return the
    verdict. `project_workspace` is a real, non-home directory the caller owns
    (a tmp dir in tests, a repo subdir for the hunter)."""
    validate_entry(entry)
    decision = evaluate_action(
        tool=entry["tool"],
        action_kind=entry["action_kind"],
        arguments=entry["arguments"],
        workspace=_workspace_for(entry["workspace"], project_workspace),
    )
    return decision.verdict


def check_entry(entry: dict[str, Any], *, project_workspace: str) -> tuple[bool, str]:
    """Return (holds, verdict): does the guard apply at least the floor
    strictness to this entry?"""
    verdict = replay_verdict(entry, project_workspace=project_workspace)
    return severity(verdict) >= severity(entry["floor"]), verdict


def load_corpus(path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL corpus file, validating every entry. Missing file -> []."""
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CorpusError(f"{path}:{lineno}: invalid JSON ({exc})") from exc
        validate_entry(entry)
        entries.append(entry)
    return entries


def iter_signatures(entries: list[dict[str, Any]]) -> Iterator[str]:
    for entry in entries:
        yield entry_signature(entry)
