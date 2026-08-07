"""custodian.hermes_guard — public OSS adapter for the Hermes Agent harness.

This package translates Hermes Agent tool-call lifecycle events into the
shared Custodian action schema and receipt protocol. It deliberately
contains no operator paths, profiles, provider configuration, credentials,
local policy choices, or machine-specific launch commands. Everything here
is reusable, versioned, and testable against a mocked Hermes event contract.

Ownership boundary (see the Custodian Hermes control handoff):

* The OSS maintainers own this adapter API and its regression tests.
* The operator owns all local deployment choices (which Hermes profile
  enables the plugin, which policy files exist, which paths are protected,
  Bubblewrap mounts) and must keep them out of this repository and any
  published artifact.

Architecture:

    Hermes pre_tool_call / transform_tool_result hooks
        -> custodian.hermes_guard.plugin   (repository-owned Hermes plugin)
        -> custodian.hermes_guard.runtime  (HermesGuardRuntime)
        -> custodian.hermes_guard.bridge   (tool vocabulary translation)
        -> custodian.codex_guard.mcp_server.evaluate_guard_action
        -> shared Custodian decision engine
        -> autonomous | escalation_required (approval) | denied, with receipts

The security decision always comes from the shared decision engine and the
operator's external Custodian service. This package never grows a parallel
personal policy engine, and the Hermes profile never contains policy logic.
"""

from __future__ import annotations

from .contract import (
    HERMES_GUARD_CONTRACT_VERSION,
    HermesDecision,
    HermesToolEvent,
    classify_tool,
    verdict_to_directive,
)
from .bridge import evaluate_tool
from .runtime import HermesGuardRuntime

__all__ = [
    "HERMES_GUARD_CONTRACT_VERSION",
    "HermesDecision",
    "HermesToolEvent",
    "HermesGuardRuntime",
    "classify_tool",
    "evaluate_tool",
    "verdict_to_directive",
]
