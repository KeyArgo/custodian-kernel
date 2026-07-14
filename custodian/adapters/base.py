"""Guard-adapter protocol: pluggable pre/post hooks around every action.

The kernel decides *whether* an action is allowed (bands, caps,
envelopes, kill switch). Guard adapters decide whether an allowed
action is *sane* — they catch the mistakes a model makes even inside
its authority: duplicate spends, leaked secrets, prompt-injected
arguments, hallucinated tools, runaway loops, drifted context.

An adapter implements two hooks:

* ``pre_action(ctx)``  — before execution. Can DENY (block), WARN
  (allow + flag), TRANSFORM (rewrite args, e.g. redact PII), or ALLOW.
* ``post_action(ctx)`` — after execution, with ``ctx.output`` set. Can
  DENY (suppress the output from reaching the model), TRANSFORM
  (rewrite the output), WARN, or ALLOW.

Adapters are deliberately synchronous, dependency-free, and small —
the same shape as cyberware's oversight scans, but composable and
category-tagged (money / security / privacy / guardrail) so a site can
enable exactly the risk surface it cares about.
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Optional


class Decision(enum.Enum):
    ALLOW = "allow"
    WARN = "warn"
    TRANSFORM = "transform"
    DENY = "deny"


# Categories an adapter can declare. Kept to a small fixed vocabulary so
# `custodian adapters list --category money` means the same thing everywhere.
CATEGORIES = ("money", "security", "privacy", "guardrail", "integration")


@dataclass
class ActionContext:
    """Everything an adapter may inspect about one proposed action.

    Mutable on purpose: TRANSFORM verdicts edit ``args``/``output`` in
    place and the pipeline carries the edited context forward.
    """

    skill: str                                  # tool/skill name, e.g. "stripe-spend"
    args: dict = field(default_factory=dict)    # proposed arguments
    band: str = "L0"                            # authority band of the request
    cost_usd: float = 0.0                       # declared cost
    session_id: str = "default"
    description: str = ""                       # model's stated intent
    output: Optional[str] = None                # set for post_action
    metadata: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def text_surface(self) -> str:
        """Every string an adapter should scan: args + description."""
        parts = [self.description]
        parts.extend(_strings_of(self.args))
        return "\n".join(p for p in parts if p)


def _strings_of(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            out.extend(_strings_of(k))
            out.extend(_strings_of(v))
        return out
    if isinstance(obj, (list, tuple, set)):
        out = []
        for v in obj:
            out.extend(_strings_of(v))
        return out
    return []


@dataclass
class Verdict:
    """One adapter's opinion of one action."""

    decision: Decision
    adapter: str
    reason: str = ""
    # For TRANSFORM: human-readable note of what changed (the change itself
    # is applied to the ActionContext in place).
    transform_note: str = ""

    @classmethod
    def allow(cls, adapter: str) -> "Verdict":
        return cls(Decision.ALLOW, adapter)

    @classmethod
    def warn(cls, adapter: str, reason: str) -> "Verdict":
        return cls(Decision.WARN, adapter, reason)

    @classmethod
    def deny(cls, adapter: str, reason: str) -> "Verdict":
        return cls(Decision.DENY, adapter, reason)

    @classmethod
    def transform(cls, adapter: str, note: str) -> "Verdict":
        return cls(Decision.TRANSFORM, adapter, transform_note=note)


class Adapter:
    """Base class for guard adapters.

    Subclasses set ``name``, ``category``, optionally ``fail_closed``,
    and override one or both hooks. Default hooks allow everything, so
    an output-only adapter just overrides ``post_action``.

    ``fail_closed=True`` means: if this adapter *raises*, the pipeline
    converts the crash into a DENY rather than skipping it. Money and
    security adapters should fail closed; convenience guards may not.
    """

    name: str = "adapter"
    category: str = "guardrail"
    version: str = "0.1.0"
    fail_closed: bool = False
    # Skills this adapter answers via handle_action(). The bridge treats
    # these as real, known tools (so the confabulation guard won't reject
    # them) even though no subprocess backs them.
    handled_skills: tuple = ()

    def __init__(self, config: Optional[dict] = None) -> None:
        self.config = config or {}

    def pre_action(self, ctx: ActionContext) -> Verdict:
        return Verdict.allow(self.name)

    def post_action(self, ctx: ActionContext) -> Verdict:
        return Verdict.allow(self.name)

    def handle_action(self, ctx: ActionContext) -> Optional[dict]:
        """Optionally *answer* the action instead of letting it reach the
        tool layer. Return a result dict to claim it, None to pass. This is
        how adapters provide capabilities (not just vetoes) — e.g. the
        Hermes introspection adapter serves `custodian-status` itself.
        Handlers run only after every pre_action hook has allowed the call."""
        return None

    def describe(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "version": self.version,
            "fail_closed": self.fail_closed,
            "doc": (self.__doc__ or "").strip().splitlines()[0] if self.__doc__ else "",
        }
