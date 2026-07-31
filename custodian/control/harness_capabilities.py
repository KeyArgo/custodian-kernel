"""Kernel-owned capability contract for harness governance adapters."""
from __future__ import annotations

from dataclasses import dataclass

from custodian.control.gate_policy import GATES


@dataclass(frozen=True)
class HarnessCapabilities:
    harness: str
    gates: frozenset[str] = GATES
    harness_specific_gates: frozenset[str] = frozenset()
    approval_transport: str = "out_of_band"
    allow_notification: str = "receipt"

    def supports(self, gate: str) -> bool:
        return gate in self.gates or gate in self.harness_specific_gates


_BUILTINS = {
    "codex": HarnessCapabilities(
        harness="codex", approval_transport="out_of_band",
        allow_notification="receipt",
    ),
    "claude": HarnessCapabilities(
        harness="claude", approval_transport="native",
        allow_notification="native",
    ),
    "opencode": HarnessCapabilities(
        harness="opencode", approval_transport="out_of_band",
        allow_notification="plugin",
    ),
    "hermes": HarnessCapabilities(
        harness="hermes", approval_transport="out_of_band",
        allow_notification="adapter",
    ),
    "talaria": HarnessCapabilities(
        harness="talaria", approval_transport="out_of_band",
        allow_notification="adapter",
    ),
}


def capabilities_for(harness: str) -> HarnessCapabilities:
    """Return a conservative common-gate contract for known or future adapters."""
    normalized = str(harness).strip().lower()
    if not normalized:
        raise ValueError("harness name is required")
    return _BUILTINS.get(normalized, HarnessCapabilities(harness=normalized))


def known_harnesses() -> tuple[str, ...]:
    return tuple(sorted(_BUILTINS))
