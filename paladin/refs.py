"""SecretRef — the zero-value pointer an agent is allowed to hold.

A ref is just ``paladin://<name>``. It is safe everywhere: logs, model
context, tool arguments, tracebacks. Nothing about the underlying value
is recoverable from it. ``repr()`` and ``str()`` are both value-free by
construction — there is no code path that can put a secret in one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCHEME = "paladin://"

# The pre-rename scheme, still accepted on read and never emitted. Every ref
# minted before the rename says ``warden://`` -- in stored policy, in skill
# configs, and in whatever the agent is still holding in context. Refusing to
# parse those would not merely fail to resolve them: `egress-domain-guard` and
# `secret-leak-guard` recognize a secret by this same scheme, so an
# unrecognized ref reads to them as "no secret present here" and the host
# restriction stops firing. Accept both, emit only SCHEME.
LEGACY_SCHEME = "warden://"
SCHEMES = (SCHEME, LEGACY_SCHEME)

# Names look like env-var-ish slugs: stripe_sk, openrouter/api_key, ...
_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127}$")

# Shared by the guards so "what a ref looks like" is defined once. Kept as a
# pattern string rather than an import, so `custodian` need not import
# `paladin` and cross the package boundary.
REF_PATTERN = (
    "(?:" + "|".join(re.escape(s) for s in SCHEMES) + ")"
    r"([a-zA-Z0-9][a-zA-Z0-9_.\-/]{0,127})"
)
_REF_RE = re.compile(REF_PATTERN)


def valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


@dataclass(frozen=True)
class SecretRef:
    """A pointer to a secret stored in a Paladin vault."""

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
        """Parse ``paladin://name`` (or a bare name) into a SecretRef.

        ``warden://name`` is also accepted -- see LEGACY_SCHEME."""
        for scheme in SCHEMES:
            if text.startswith(scheme):
                text = text[len(scheme):]
                break
        return cls(text)


def find_refs(text: str) -> list[SecretRef]:
    """Extract every paladin:// (or legacy warden://) ref appearing in a blob
    of text — used by the Hermes bridge to discover which secrets a tool call
    wants."""
    return [SecretRef(m.group(1)) for m in _REF_RE.finditer(text)]
