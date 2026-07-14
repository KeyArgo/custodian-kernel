"""AdapterPipeline — runs every enabled adapter around one action.

Ordering and semantics:

* Adapters run in registration order. A DENY short-circuits: later
  adapters don't run, the action is blocked.
* TRANSFORM verdicts chain — each adapter sees the previous adapter's
  edits (e.g. PII redaction happens before secret-leak scanning).
* WARNs accumulate; the action proceeds but every warning is attached
  to the result (and should end up in the receipt/audit trail).
* An adapter that *raises* is a bug, not a policy statement: the crash
  becomes a DENY if the adapter declared ``fail_closed``, otherwise a
  WARN naming the adapter. Either way the pipeline never dies mid-run.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from custodian.adapters.base import ActionContext, Adapter, Decision, Verdict


@dataclass
class PipelineResult:
    allowed: bool
    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def denials(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.decision == Decision.DENY]

    @property
    def warnings(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.decision == Decision.WARN]

    @property
    def transforms(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.decision == Decision.TRANSFORM]

    def summary(self) -> str:
        if self.allowed and not self.verdicts:
            return "allow (no adapters enabled)"
        bits = []
        for v in self.verdicts:
            if v.decision == Decision.ALLOW:
                continue
            note = v.reason or v.transform_note
            bits.append(f"{v.adapter}:{v.decision.value}({note})")
        return "; ".join(bits) if bits else "allow"


class AdapterPipeline:
    def __init__(self, adapters: list[Adapter] | None = None) -> None:
        self.adapters: list[Adapter] = list(adapters or [])

    def add(self, adapter: Adapter) -> "AdapterPipeline":
        self.adapters.append(adapter)
        return self

    def _run(self, hook_name: str, ctx: ActionContext) -> PipelineResult:
        verdicts: list[Verdict] = []
        for adapter in self.adapters:
            hook = getattr(adapter, hook_name)
            try:
                v = hook(ctx)
            except Exception as e:  # adapter bug — contain it
                if adapter.fail_closed:
                    v = Verdict.deny(adapter.name,
                                     f"adapter crashed ({type(e).__name__}: {e}) — fail-closed")
                else:
                    v = Verdict.warn(adapter.name,
                                     f"adapter crashed ({type(e).__name__}: {e}) — skipped")
            verdicts.append(v)
            if v.decision == Decision.DENY:
                return PipelineResult(allowed=False, verdicts=verdicts)
        return PipelineResult(allowed=True, verdicts=verdicts)

    def run_pre(self, ctx: ActionContext) -> PipelineResult:
        return self._run("pre_action", ctx)

    def run_post(self, ctx: ActionContext) -> PipelineResult:
        return self._run("post_action", ctx)

    def handle(self, ctx: ActionContext):
        """Give each adapter the chance to answer the action itself.
        First non-None result wins; None means no adapter claimed it.
        A crash in a handler falls through to the next one — providing a
        capability is opt-in, so failing to provide it is never fatal."""
        for adapter in self.adapters:
            try:
                result = adapter.handle_action(ctx)
            except Exception:
                continue
            if result is not None:
                return result
        return None
