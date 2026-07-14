"""ToolConfabulationGuard — blocks calls to tools that don't exist.

Local models confabulate: they invoke ``stripe-refund-all`` (not a
tool), pass ``amount_dollars`` where the schema says ``amount``, or
merge two half-remembered tool names into one. Executing a guessed call
is how "the model made a typo" becomes "the model did the wrong thing
with real side effects".

Given the site's tool inventory (from Custodian's ToolRegistry or any
{name: [arg names]} map), this guard:

* DENIES calls to unknown skills — and, because the model will retry,
  the denial message lists close-match suggestions (`did you mean …`)
  so the retry converges instead of thrashing.
* DENIES calls with unknown argument names when the schema is known,
  naming the valid ones.

Everything it needs lives outside the model, so it keeps working when
the model's memory of the tool list is long gone.
"""
from __future__ import annotations

import difflib

from custodian.adapters.base import ActionContext, Adapter, Verdict


class ToolConfabulationGuard(Adapter):
    """Denies hallucinated tool names and argument names."""

    name = "tool-confabulation-guard"
    category = "guardrail"
    fail_closed = True

    def __init__(self, config: dict | None = None,
                 inventory: dict[str, list[str]] | None = None) -> None:
        """`inventory` maps skill name → known argument names. An empty
        arg list means "args unknown, don't validate them"."""
        super().__init__(config)
        self.inventory: dict[str, list[str]] = dict(inventory or {})
        # Args every skill implicitly accepts (bridge plumbing).
        self.common_args = set(self.config.get("common_args",
                                               ["description", "session_id"]))

    @classmethod
    def from_registry(cls, registry, config: dict | None = None):
        """Build the inventory from a custodian.tools.registry.ToolRegistry."""
        inventory = {t.name: [] for t in registry.all()}
        return cls(config=config, inventory=inventory)

    def pre_action(self, ctx: ActionContext) -> Verdict:
        if not self.inventory:
            return Verdict.allow(self.name)  # no inventory wired — nothing to check

        if ctx.skill not in self.inventory:
            suggestions = difflib.get_close_matches(ctx.skill, self.inventory, n=3, cutoff=0.6)
            hint = f" — did you mean: {', '.join(suggestions)}?" if suggestions else ""
            return Verdict.deny(
                self.name,
                f"no tool named {ctx.skill!r} exists{hint} "
                f"(the tool list is authoritative; do not invent tool names)",
            )

        known_args = set(self.inventory[ctx.skill])
        if known_args:
            unknown = set(ctx.args) - known_args - self.common_args
            if unknown:
                return Verdict.deny(
                    self.name,
                    f"{ctx.skill!r} has no argument(s) {sorted(unknown)} — "
                    f"valid arguments: {sorted(known_args)}",
                )
        return Verdict.allow(self.name)
