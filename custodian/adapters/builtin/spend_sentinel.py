"""SpendSentinel — anomaly detection layered over the kernel's caps.

The kernel already enforces *limits* (bands, per-action caps, daily
envelopes, margins). SpendSentinel catches spends that are within
limits but *wrong*:

* **Duplicates** — the same amount + normalized description inside a
  window. The classic context-lossy local model failure: it forgets it
  already paid and pays again. Denied.
* **Velocity** — more than N spend actions per minute in one session.
  A loop that happens to spend money. Denied.
* **Escalation crawl** — a run of strictly increasing amounts (a model
  probing for its cap). Warned, so the receipt trail shows the pattern.

State is in-memory per pipeline instance (one agent session). Money
adapters fail closed: a crash in here blocks the spend.
"""
from __future__ import annotations

import re
import time

from custodian.adapters.base import ActionContext, Adapter, Verdict

_SPEND_SKILLS_DEFAULT = ("stripe-spend", "stripe-refund", "stripe-payout",
                         "stripe-invoice-send", "modal-invoke", "modal-run",
                         "nim-job-submit")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class SpendSentinel(Adapter):
    """Blocks duplicate spends, spend loops, and cap-probing patterns."""

    name = "spend-sentinel"
    category = "money"
    fail_closed = True

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.spend_skills = tuple(self.config.get("spend_skills", _SPEND_SKILLS_DEFAULT))
        self.duplicate_window_s = float(self.config.get("duplicate_window_s", 600))
        self.max_per_minute = int(self.config.get("max_per_minute", 6))
        self.escalation_run = int(self.config.get("escalation_run", 4))
        # (ts, amount, normalized description)
        self._history: list[tuple[float, float, str]] = []

    def _is_spend(self, ctx: ActionContext) -> bool:
        return ctx.skill in self.spend_skills or ctx.cost_usd > 0

    def pre_action(self, ctx: ActionContext) -> Verdict:
        if not self._is_spend(ctx):
            return Verdict.allow(self.name)

        now = ctx.ts or time.time()
        amount = float(ctx.args.get("amount", ctx.cost_usd) or 0)
        desc = _norm(str(ctx.args.get("description", ctx.description)))

        recent = [(t, a, d) for t, a, d in self._history
                  if now - t <= self.duplicate_window_s]

        # Duplicate spend: same amount + same description in the window.
        # The trailing `and desc` used to skip this check entirely for an
        # empty description -- ctx.description defaults to "", so a spend
        # call that never sets one (a real, easily-reached shape, not an
        # edge case) got zero duplicate protection: 5 identical $25.00
        # spends with an empty description, 2 minutes apart, all allowed.
        # Two spends of the same amount with the same (even blank)
        # description within the window is exactly the duplicate-payment
        # signature this adapter exists to catch -- found in review.
        for t, a, d in recent:
            if a == amount and d == desc:
                return Verdict.deny(
                    self.name,
                    f"duplicate spend: {amount:.2f} for {desc!r} already requested "
                    f"{int(now - t)}s ago — if intentional, change the description",
                )

        # Velocity: too many spends in the last minute.
        last_minute = [t for t, _, _ in recent if now - t <= 60]
        if len(last_minute) + 1 > self.max_per_minute:
            return Verdict.deny(
                self.name,
                f"spend velocity: {len(last_minute) + 1} spend actions in 60s "
                f"(max {self.max_per_minute}) — looks like a loop",
            )

        self._history.append((now, amount, desc))

        # Escalation crawl: strictly increasing run of amounts.
        amounts = [a for _, a, _ in self._history[-self.escalation_run:]]
        if (len(amounts) >= self.escalation_run
                and all(b > a for a, b in zip(amounts, amounts[1:]))):
            return Verdict.warn(
                self.name,
                f"escalating amounts {amounts} — pattern resembles cap probing",
            )

        return Verdict.allow(self.name)
