"""SecretLeakGuard — stops credentials from entering or leaving the agent.

Two detection layers:

1. **Format scan** — well-known key shapes (Stripe, AWS, GitHub, Slack,
   OpenAI/OpenRouter, private key blocks, JWTs) plus a Shannon-entropy
   check on long opaque tokens. Applied to *both* directions: arguments
   (agent trying to send a credential somewhere) and outputs (a
   credential coming back into model context).
2. **Paladin tripwire** — if a :class:`paladin.broker.LeakSentinel` is
   provided, every token is hashed and checked against the values Paladin
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

_TOKEN_SPLIT = re.compile(r"[\s\"'`,;=(){}\[\]<>/\\.?&:]+")
# '.', '?', '&', ':' added: sentence punctuation ("the credential X. please
# retry") and URL query separators ("?key=X&y=1") merged the actual secret
# into a token that matched neither the paladin tripwire's exact-value hash
# nor (once diluted by the extra low-information characters) the
# high-entropy fallback threshold -- so a secret sitting next to any of
# these characters produced zero findings. Deliberately NOT splitting on
# '-', '_', '+': those are legitimate interior characters for token shapes
# this guard already recognizes (sk-..., gh[pousr]_..., xox[baprs]-...,
# base64's '+'), so splitting on them would fragment real tokens instead
# of isolating them. Found in review.

# A ref is a zero-value pointer, so its name is exempt from the high-entropy
# check — a long secret name is not a leaked secret. Matched against the RAW
# text, never against tokens: _TOKEN_SPLIT deliberately splits on "/" (see
# _findings), so no token ever retains a "paladin://" prefix and a
# startswith() test here is unreachable dead code. The pre-rename scheme is
# accepted because refs minted before the rename are still in circulation.
_REF_RE = re.compile(r"(?:paladin|warden)://([a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127})")


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _scan(text: str, sentinel) -> list[tuple[str, str]]:
    """Return [(matched_text, label)] for every finding in `text`.

    _TOKEN_SPLIT includes '/' and '\\' (path separators) specifically so
    the high-entropy fallback below evaluates path SEGMENTS rather than
    a whole filesystem path as one token. Confirmed live against a real
    Hermes Agent session: an ordinary file-write to a path containing a
    UUID-bearing temp directory (e.g. .../0192eba3-ffe3-.../file.txt —
    common for session/container/scratch dirs) was a false positive
    before this fix, because the *whole path* (80+ chars, high per-char
    entropy from the hex+dash UUID) tripped the len>=32/entropy>=4.5
    threshold. Once split on '/', the UUID segment alone (36 chars,
    entropy ~3.8) falls under the threshold — while a genuine freestanding
    credential (which is never itself a filesystem path) is unaffected
    either way.
    """
    findings = []
    for pattern, label in _PATTERNS:
        for m in pattern.finditer(text):
            findings.append((m.group(0), label))
    # Ref names, collected from the raw text before tokenizing (see _REF_RE).
    # A name may itself contain '/' (openrouter/api_key), so split it the same
    # way the text is split or its segments won't match.
    exempt = set()
    for m in _REF_RE.finditer(text):
        exempt.update(_TOKEN_SPLIT.split(m.group(1)))
    for token in _TOKEN_SPLIT.split(text):
        # Order matters: a token the sentinel has seen is a real vault VALUE
        # and stays a finding even if it also appears as a ref name.
        if sentinel is not None and sentinel.seen(token):
            findings.append((token, "paladin-vault-value"))
        elif (len(token) >= 32 and _entropy(token) >= 4.5
              and token not in exempt):
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
                f"use a paladin:// ref instead of a raw value",
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
