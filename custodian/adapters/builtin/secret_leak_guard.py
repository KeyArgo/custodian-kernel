"""SecretLeakGuard — stops credentials from entering or leaving the agent.

Two detection layers:

1. **Format scan** — well-known key shapes (Stripe, AWS, GitHub, Slack,
   OpenAI/OpenRouter, private key blocks, JWTs) plus a Shannon-entropy
   check on long opaque tokens. Applied to *both* directions: arguments
   (agent trying to send a credential somewhere) and outputs (a
   credential coming back into model context).
2. **Caduceus tripwire** — if a :class:`caduceus.broker.LeakSentinel` is
   provided, every token is hashed and checked against the values Caduceus
   actually released. This catches the worst case precisely: a secret
   the agent was never shown, surfacing in its context anyway (echoed by
   a subprocess, printed in an error, reflected by an API).

Verdicts: leaks in arguments DENY (the send doesn't happen); leaks in
output TRANSFORM (the secret is replaced with ``[REDACTED:<label>]``
before the model sees it) plus WARN metadata via the transform note.
"""
from __future__ import annotations

import math
import re

from custodian.adapters.base import ActionContext, Adapter, Verdict

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{10,}\b"), "stripe-secret-key"),
    (re.compile(r"\brk_(live|test)_[A-Za-z0-9]{10,}\b"), "stripe-restricted-key"),
    (re.compile(r"\bwhsec_[A-Za-z0-9]{16,}\b"), "stripe-webhook-secret"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws-access-key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "github-token"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "slack-token"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "openai-style-key"),
    (re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}\b"), "nvidia-api-key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private-key-block"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "jwt"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "google-api-key"),
]

_TOKEN_SPLIT = re.compile(r"[\s\"'`,;=(){}\[\]<>]+")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _scan(text: str, sentinel) -> list[tuple[str, str]]:
    """Return [(matched_text, label)] for every finding in `text`."""
    findings = []
    for pattern, label in _PATTERNS:
        for m in pattern.finditer(text):
            findings.append((m.group(0), label))
    for token in _TOKEN_SPLIT.split(text):
        if sentinel is not None and sentinel.seen(token):
            findings.append((token, "caduceus-vault-value"))
        elif len(token) >= 32 and _entropy(token) >= 4.5 and not token.startswith("caduceus://"):
            findings.append((token, "high-entropy-token"))
    return findings


class SecretLeakGuard(Adapter):
    """Denies credential egress in args; redacts credentials in output."""

    name = "secret-leak-guard"
    category = "security"
    fail_closed = True

    def __init__(self, config: dict | None = None, leak_sentinel=None) -> None:
        super().__init__(config)
        self.leak_sentinel = leak_sentinel

    def pre_action(self, ctx: ActionContext) -> Verdict:
        findings = _scan(ctx.text_surface(), self.leak_sentinel)
        if findings:
            labels = sorted({label for _, label in findings})
            return Verdict.deny(
                self.name,
                f"credential material in tool arguments ({', '.join(labels)}) — "
                f"use a caduceus:// ref instead of a raw value",
            )
        return Verdict.allow(self.name)

    def post_action(self, ctx: ActionContext) -> Verdict:
        if not ctx.output:
            return Verdict.allow(self.name)
        findings = _scan(ctx.output, self.leak_sentinel)
        if not findings:
            return Verdict.allow(self.name)
        redacted = ctx.output
        for text, label in findings:
            redacted = redacted.replace(text, f"[REDACTED:{label}]")
        ctx.output = redacted
        labels = sorted({label for _, label in findings})
        return Verdict.transform(
            self.name, f"redacted {len(findings)} credential(s) from output "
                       f"({', '.join(labels)})"
        )
