"""ContextAnchor — invariants that survive the model forgetting them.

Local models drop context: quantized weights, small windows, aggressive
truncation. Ten turns in, the model has forgotten the budget, the task,
or the "never touch prod" constraint it was told at turn one. Prompts
can't fix this — anything in the prompt is exactly what gets truncated.

ContextAnchor holds the invariants *outside* the model:

* ``goal``        — what this session is for.
* ``constraints`` — plain-text rules the operator set.
* ``forbidden_skills`` / ``allowed_skills`` — hard skill fences that
  are *enforced* at pre_action, not merely restated in the prompt.
* ``max_session_cost_usd`` — a cumulative meter this adapter tracks
  itself; it denies when total declared cost would cross it, whether or
  not the model remembers spending.

``anchor_block()`` renders the invariants as a compact text block. The
Hermes bridge re-injects it every N turns and after any context reset —
so the model is *reminded* — but enforcement never depends on the
reminder landing.
"""
from __future__ import annotations

from custodian.adapters.base import ActionContext, Adapter, Verdict


class ContextAnchor(Adapter):
    """Enforces session invariants regardless of what the model remembers."""

    name = "context-anchor"
    category = "guardrail"
    fail_closed = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.goal: str = self.config.get("goal", "")
        self.constraints: list[str] = list(self.config.get("constraints", []))
        self.allowed_skills = set(self.config.get("allowed_skills", []))  # empty = any
        self.forbidden_skills = set(self.config.get("forbidden_skills", []))
        self.max_session_cost_usd = float(self.config.get("max_session_cost_usd", 0) or 0)
        self.session_cost_usd: float = 0.0
        self.actions_seen: int = 0

    def pre_action(self, ctx: ActionContext) -> Verdict:
        self.actions_seen += 1

        if ctx.skill in self.forbidden_skills:
            return Verdict.deny(
                self.name,
                f"skill {ctx.skill!r} is forbidden for this session "
                f"(session invariant, set at start — this does not expire "
                f"when context is lost)",
            )
        if self.allowed_skills and ctx.skill not in self.allowed_skills:
            return Verdict.deny(
                self.name,
                f"skill {ctx.skill!r} is outside this session's allowed set "
                f"{sorted(self.allowed_skills)}",
            )
        if self.max_session_cost_usd and ctx.cost_usd:
            if self.session_cost_usd + ctx.cost_usd > self.max_session_cost_usd:
                return Verdict.deny(
                    self.name,
                    f"session budget: {self.session_cost_usd:.2f} spent of "
                    f"{self.max_session_cost_usd:.2f} — this {ctx.cost_usd:.2f} "
                    f"action would exceed it",
                )
            self.session_cost_usd += ctx.cost_usd
        return Verdict.allow(self.name)

    # -- re-anchoring surface (used by the Hermes bridge) ----------------------

    def anchor_block(self) -> str:
        """Compact invariant block to re-inject into a drifting model."""
        lines = ["[SESSION INVARIANTS — restated by Custodian, authoritative]"]
        if self.goal:
            lines.append(f"Goal: {self.goal}")
        for c in self.constraints:
            lines.append(f"Constraint: {c}")
        if self.allowed_skills:
            lines.append(f"Allowed skills: {', '.join(sorted(self.allowed_skills))}")
        if self.forbidden_skills:
            lines.append(f"Forbidden skills: {', '.join(sorted(self.forbidden_skills))}")
        if self.max_session_cost_usd:
            lines.append(
                f"Budget: ${self.session_cost_usd:.2f} spent of "
                f"${self.max_session_cost_usd:.2f} — remaining "
                f"${self.max_session_cost_usd - self.session_cost_usd:.2f}"
            )
        lines.append("These invariants are enforced outside your process; "
                     "actions violating them will be denied.")
        return "\n".join(lines)
