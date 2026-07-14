"""PromptInjectionGuard — scans tool arguments for injection payloads.

Tool arguments frequently contain text that originated *outside* the
operator's control: web pages, emails, ticket bodies, file contents.
This guard scans the action's text surface for the signatures of an
instruction-override attempt before the action executes with those
arguments — the point where injected text turns into real side effects.

This is heuristic, not a classifier: it catches the widespread, blunt
injection families (instruction overrides, role hijacks, exfil URLs,
smuggled base64 blobs) and deliberately prefers WARN over DENY for the
ambiguous ones. Sites can tighten with ``config={"strict": True}``,
which upgrades every WARN to DENY.
"""
from __future__ import annotations

import base64
import re

from custodian.adapters.base import ActionContext, Adapter, Verdict

# (pattern, is_hard_deny, label)
_RULES: list[tuple[re.Pattern, bool, str]] = [
    (re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above)\s+(instructions|prompts|rules)", re.I),
     True, "instruction override"),
    (re.compile(r"disregard\s+(your|the)\s+(system\s+prompt|instructions|rules|guidelines)", re.I),
     True, "instruction override"),
    (re.compile(r"you\s+are\s+now\s+(?:\w+\s+){0,3}(?:mode|persona|jailbroken|DAN)", re.I),
     True, "role hijack"),
    (re.compile(r"(reveal|print|show|output|repeat)\s+(your|the)\s+(system\s+prompt|instructions|api\s*key|secret|credential)", re.I),
     True, "exfiltration request"),
    (re.compile(r"do\s+not\s+(tell|inform|alert|notify)\s+(the\s+)?(user|human|operator)", re.I),
     True, "concealment request"),
    (re.compile(r"https?://[^\s]*[?&](key|token|secret|password|auth)=", re.I),
     True, "credential in URL"),
    (re.compile(r"\bnew\s+instructions?\s*:", re.I), False, "inline instruction block"),
    (re.compile(r"<\s*/?\s*system\s*>", re.I), False, "fake system tag"),
    (re.compile(r"\bIMPORTANT\s*:\s*you\s+must\b", re.I), False, "urgency override"),
]

# 40+ base64 chars decodes to ~30 bytes — enough to carry a short override
# like "ignore all previous instructions". A decoded blob is only ever
# *denied* when it itself matches an injection rule, so a low threshold adds
# no false positives, only coverage.
_B64_BLOB = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


class PromptInjectionGuard(Adapter):
    """Blocks tool calls whose arguments carry injection signatures."""

    name = "prompt-injection-guard"
    category = "security"
    fail_closed = True

    def pre_action(self, ctx: ActionContext) -> Verdict:
        surface = ctx.text_surface()
        strict = bool(self.config.get("strict", False))

        for pattern, hard, label in _RULES:
            if pattern.search(surface):
                if hard or strict:
                    return Verdict.deny(self.name, f"{label} detected in tool arguments")
                return Verdict.warn(self.name, f"possible {label} in tool arguments")

        # Large base64 blobs in args are a common smuggling channel — decode
        # and re-scan; if the payload itself trips a rule, deny.
        for blob in _B64_BLOB.findall(surface)[:5]:
            try:
                decoded = base64.b64decode(blob, validate=True).decode("utf-8", "ignore")
            except Exception:
                continue
            for pattern, _, label in _RULES:
                if pattern.search(decoded):
                    return Verdict.deny(
                        self.name, f"{label} hidden in base64-encoded argument"
                    )

        return Verdict.allow(self.name)
