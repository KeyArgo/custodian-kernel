"""PiiRedactor — keeps personal data out of model context and egress.

Detects emails, phone numbers, SSNs, credit card numbers (Luhn-checked
to avoid mangling order IDs), and IP addresses. Findings in *output*
are redacted in place (TRANSFORM) so the model never ingests them;
findings in *arguments* are redacted too by default, or denied outright
with ``config={"deny_on_args": True}`` for sites where PII must never
ride in a tool call at all.

Config:
    kinds        — subset of {email, phone, ssn, card, ip} (default all)
    deny_on_args — deny instead of redacting when PII appears in args
    allowlist    — exact strings to ignore (e.g. the operator's own
                   support email that legitimately appears everywhere)
"""
from __future__ import annotations

import re

from custodian.adapters.base import ActionContext, Adapter, Verdict

_DETECTORS: dict[str, re.Pattern] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<![\d.])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\d.])"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "ip": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
}


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        alt = not alt
    return total % 10 == 0


class PiiRedactor(Adapter):
    """Redacts (or blocks) personal data flowing through actions."""

    name = "pii-redactor"
    category = "privacy"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        kinds = self.config.get("kinds", list(_DETECTORS))
        self.detectors = {k: _DETECTORS[k] for k in kinds if k in _DETECTORS}
        self.deny_on_args = bool(self.config.get("deny_on_args", False))
        self.allowlist = set(self.config.get("allowlist", []))

    def _findings(self, text: str) -> list[tuple[str, str]]:
        out = []
        for kind, pattern in self.detectors.items():
            for m in pattern.finditer(text):
                token = m.group(0)
                if token in self.allowlist:
                    continue
                if kind == "card":
                    digits = re.sub(r"[ -]", "", token)
                    if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                        continue
                if kind == "ip" and token.startswith(("10.", "127.", "192.168.", "0.")):
                    continue  # infra addresses, not personal data
                out.append((token, kind))
        return out

    @staticmethod
    def _redact(text: str, findings: list[tuple[str, str]]) -> str:
        for token, kind in findings:
            text = text.replace(token, f"[PII:{kind}]")
        return text

    def pre_action(self, ctx: ActionContext) -> Verdict:
        findings = self._findings(ctx.text_surface())
        if not findings:
            return Verdict.allow(self.name)
        kinds = sorted({k for _, k in findings})
        if self.deny_on_args:
            return Verdict.deny(self.name, f"PII in tool arguments ({', '.join(kinds)})")
        for key, value in list(ctx.args.items()):
            if isinstance(value, str):
                ctx.args[key] = self._redact(value, findings)
        ctx.description = self._redact(ctx.description, findings)
        return Verdict.transform(
            self.name, f"redacted {len(findings)} PII item(s) from arguments "
                       f"({', '.join(kinds)})"
        )

    def post_action(self, ctx: ActionContext) -> Verdict:
        if not ctx.output:
            return Verdict.allow(self.name)
        findings = self._findings(ctx.output)
        if not findings:
            return Verdict.allow(self.name)
        ctx.output = self._redact(ctx.output, findings)
        kinds = sorted({k for _, k in findings})
        return Verdict.transform(
            self.name, f"redacted {len(findings)} PII item(s) from output "
                       f"({', '.join(kinds)})"
        )
