"""Soul compiler — SOUL.md sections generated from enforced state.

A hand-written system prompt drifts away from the policy that actually
runs: the prompt says "$2 cap" while policy.yaml says $5, and the model
reasons from the wrong number. This module renders the authority
section of the Hermes system prompt *from* the live policy + capsule,
so what the model is told always equals what the kernel enforces.

Usage::

    from talaria.soul import compile_soul_section
    section = compile_soul_section(policy_path="policy.yaml", capsule=capsule)
    soul = base_soul_text + "\n\n" + section
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml


def _policy_facts(policy_path: str | Path) -> list[str]:
    """Extract prompt-worthy facts from a Custodian policy.yaml."""
    doc = yaml.safe_load(Path(policy_path).read_text()) or {}
    facts: list[str] = []

    authority = doc.get("authority", doc)
    band = authority.get("band")
    if band:
        facts.append(f"Your authority band is {band}.")
    cap = authority.get("per_action_cap", authority.get("cap"))
    if cap is not None:
        facts.append(f"Per-action spend cap: ${float(cap):.2f}. Anything above "
                     f"escalates to a human — call the skill anyway and let it escalate.")
    session_cap = authority.get("session_cap")
    if session_cap is not None:
        facts.append(f"Session spend cap: ${float(session_cap):.2f}.")

    directives = doc.get("directives", {})
    envelope = directives.get("daily_envelope")
    if envelope is not None:
        facts.append(f"Rolling 24-hour envelope: ${float(envelope):.2f} total.")
    margins = directives.get("margins", {})
    if margins.get("minimum_margin") is not None:
        facts.append(f"Minimum margin: ${float(margins['minimum_margin']):.2f}"
                     + (f" ({margins['minimum_margin_pct']}%)"
                        if margins.get("minimum_margin_pct") else "") + ".")
    policies = doc.get("policies", directives.get("policies", {}))
    if policies.get("no_self_dealing"):
        facts.append("No self-dealing: you cannot pay accounts you control.")
    return facts


def compile_soul_section(policy_path: Optional[str | Path] = None,
                         capsule=None, warden_enabled: bool = False) -> str:
    """Render the authority section of SOUL.md from live state."""
    lines = [
        "## Your authority (generated — matches the enforced policy exactly)",
        "",
        "You operate under a kernel that enforces every limit below OUTSIDE "
        "your process. These are not requests; actions beyond them are "
        "denied mechanically. Reason from these numbers, never from memory.",
        "",
    ]
    if policy_path and Path(policy_path).exists():
        for fact in _policy_facts(policy_path):
            lines.append(f"- {fact}")
    if capsule is not None:
        if capsule.goal:
            lines.append(f"- Session goal: {capsule.goal}")
        for c in capsule.constraints:
            lines.append(f"- {c}")
        if capsule.max_session_cost_usd:
            lines.append(f"- Session budget: ${capsule.max_session_cost_usd:.2f} "
                         f"(${capsule.spent_usd:.2f} already spent).")
    if warden_enabled:
        lines += [
            "- Credentials are managed by Warden. You will see `warden://` "
            "references — use them exactly as given in tool arguments. You "
            "cannot read, print, or export the underlying values, and tool "
            "output containing credentials is redacted before you see it. "
            "Never ask the user to paste a raw key into the conversation.",
        ]
    lines += [
        "",
        "If an action is denied, the denial reason tells you what to change. "
        "Denials are final for identical retries — vary your approach or "
        "report the blocker.",
    ]
    return "\n".join(lines)
