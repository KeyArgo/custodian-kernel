"""RepetitionBreaker — kills the loops context-lossy models fall into.

The signature failure of a small local model: it forgets it already
tried something and tries it again. And again. Three shapes show up in
practice:

* **Hammering** — identical skill+args K times in a window.
* **Ping-pong** — an A-B-A-B alternation (try, check, try, check...)
  that never terminates.
* **Churn** — the same skill called with trivially-varied args many
  times in a short burst (retry storms with jittered wording).
* **Scatter** — many actions in a short window with no single repeated
  skill or exact call to pin down (rotating across enough distinct
  skills/args defeats the three shapes above, which all require some
  concrete thing — a fingerprint, an A/B pair, one skill name — to
  repeat; a model burning through unrelated tool calls without
  converging is still a loop even though nothing about it repeats
  exactly. Verified live: 50 calls across 5 rotating skill names with a
  unique arg each time produced zero denials from the other three
  checks. Found in review).

The breaker's DENY message is written *for the model*: it states what
was repeated and instructs it to change strategy — which, injected back
as a tool error, is usually enough to knock a looping model onto a new
path. The count thresholds reset naturally as the window slides.
"""
from __future__ import annotations

import hashlib
import json
import time

from custodian.adapters.base import ActionContext, Adapter, Verdict


def _fingerprint(ctx: ActionContext) -> str:
    body = json.dumps({"skill": ctx.skill, "args": ctx.args}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


class RepetitionBreaker(Adapter):
    """Denies hammering, ping-pong cycles, and retry churn."""

    name = "repetition-breaker"
    category = "guardrail"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.window_s = float(self.config.get("window_s", 300))
        self.max_identical = int(self.config.get("max_identical", 3))
        self.max_pingpong = int(self.config.get("max_pingpong", 3))  # A-B pairs
        self.max_same_skill_burst = int(self.config.get("max_same_skill_burst", 10))
        self.max_total_burst = int(self.config.get("max_total_burst", 20))
        self._history: list[tuple[float, str, str]] = []  # (ts, fingerprint, skill)

    def pre_action(self, ctx: ActionContext) -> Verdict:
        now = ctx.ts or time.time()
        fp = _fingerprint(ctx)
        self._history = [(t, f, s) for t, f, s in self._history if now - t <= self.window_s]

        identical = sum(1 for _, f, _ in self._history if f == fp)
        if identical + 1 > self.max_identical:
            return Verdict.deny(
                self.name,
                f"identical call to {ctx.skill!r} attempted {identical + 1} times in "
                f"{int(self.window_s)}s — the previous attempts already ran; do not "
                f"retry this exact call, change your approach or report the blocker",
            )

        fps = [f for _, f, _ in self._history] + [fp]
        if len(fps) >= self.max_pingpong * 2:
            tail = fps[-self.max_pingpong * 2:]
            a, b = tail[0], tail[1]
            if a != b and tail == [a, b] * self.max_pingpong:
                return Verdict.deny(
                    self.name,
                    f"ping-pong loop detected ({self.max_pingpong}× alternation on "
                    f"{ctx.skill!r}) — the cycle is not converging; stop and "
                    f"summarize what you have learned instead",
                )

        burst = sum(1 for t, _, s in self._history if s == ctx.skill and now - t <= 60)
        if burst + 1 > self.max_same_skill_burst:
            return Verdict.deny(
                self.name,
                f"{burst + 1} calls to {ctx.skill!r} in 60s — retry storm; "
                f"back off and reconsider",
            )

        # Scatter: no single skill/fingerprint repeats enough to trip the
        # checks above, but the total call rate is still a loop.
        total_burst = sum(1 for t, _, _ in self._history if now - t <= 60)
        if total_burst + 1 > self.max_total_burst:
            return Verdict.deny(
                self.name,
                f"{total_burst + 1} actions in 60s across {len({s for _, _, s in self._history})} "
                f"different skills — this looks like a non-converging loop even though no "
                f"single call repeats; stop and summarize what you have learned instead",
            )

        self._history.append((now, fp, ctx.skill))
        return Verdict.allow(self.name)
