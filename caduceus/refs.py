"""SecretRef — the zero-value pointer an agent is allowed to hold.

A ref is just ``caduceus://<name>``. It is safe everywhere: logs, model
context, tool arguments, tracebacks. Nothing about the underlying value
is recoverable from it. ``repr()`` and ``str()`` are both value-free by
construction — there is no code path that can put a secret in one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCHEME = "caduceus://"
# Names look like env-var-ish slugs: stripe_sk, openrouter/api_key, ...
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127}$")


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


@dataclass(frozen=True)
class SecretRef:
    """A pointer to a secret stored in a Caduceus vault."""

    name: str

    def __post_init__(self) -> None:
        if not valid_name(self.name):
            raise ValueError(
                f"invalid secret name {self.name!r}: must match {_NAME_RE.pattern}"
            )

    @property
    def uri(self) -> str:
        return f"{SCHEME}{self.name}"

    def __str__(self) -> str:
        return self.uri

    def __repr__(self) -> str:
        return f"SecretRef({self.uri})"

    @classmethod
    def parse(cls, text: str) -> "SecretRef":
        """Parse ``caduceus://name`` (or a bare name) into a SecretRef."""
        if text.startswith(SCHEME):
            text = text[len(SCHEME):]
        return cls(text)


def find_refs(text: str) -> list[SecretRef]:
    """Extract every caduceus:// ref appearing in a blob of text — used by
    the Hermes bridge to discover which secrets a tool call wants."""
    out = []
    for m in re.finditer(re.escape(SCHEME) + r"([a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127})", text):
        out.append(SecretRef(m.group(1)))
    return out
