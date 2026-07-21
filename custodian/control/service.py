"""Control-plane service: orchestrates shared event flow, component
registration, and enforcement-level reporting for all integrations.

Codex, Talaria/Hermes, Paladin, and the executor each emit and consume
the same normalized events through this service.  There is exactly one
shared gate — no adapter-specific competing approval gate.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from custodian.control.contracts import (
    ControlDecision,
    ControlEvent,
    EnforcementLevel,
    new_correlation_id,
)


@dataclass
class ComponentRegistration:
    component: str
    identity: str
    enforcement: EnforcementLevel = EnforcementLevel.ROUTED
    registered_at: float = 0.0
    healthy: bool = True
    last_seen: float = 0.0


class ControlService:
    """Central control-plane coordinator.

    Maintains a lightweight in-memory event log (bounded), a registry of
    active components, and produces normalized decisions.  Intended to be
    embedded inside the operator service process; production deployments
    should back the event log with the universal ledger.
    """

    def __init__(self, max_events: int = 10000) -> None:
        self._registry: dict[str, ComponentRegistration] = {}
        self._events: list[ControlEvent] = []
        self._max_events = max_events

    # -- Component lifecycle ------------------------------------------------

    def register(
        self,
        component: str,
        identity: str,
        enforcement: EnforcementLevel = EnforcementLevel.ROUTED,
    ) -> ComponentRegistration:
        now = time.time()
        reg = ComponentRegistration(
            component=component,
            identity=identity,
            enforcement=enforcement,
            registered_at=now,
            healthy=True,
            last_seen=now,
        )
        self._registry[f"{component}:{identity}"] = reg
        return reg

    def unregister(self, component: str, identity: str) -> bool:
        key = f"{component}:{identity}"
        if key in self._registry:
            del self._registry[key]
            return True
        return False

    def list_components(self) -> list[ComponentRegistration]:
        return list(self._registry.values())

    def get_component(
        self, component: str, identity: str
    ) -> Optional[ComponentRegistration]:
        return self._registry.get(f"{component}:{identity}")

    def heartbeat(self, component: str, identity: str) -> None:
        reg = self._registry.get(f"{component}:{identity}")
        if reg is not None:
            reg.last_seen = time.time()
            reg.healthy = True

    # -- Events -------------------------------------------------------------

    def emit(self, event: ControlEvent) -> ControlEvent:
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events.pop(0)
        return event

    def query_by_correlation(self, correlation_id: str) -> list[ControlEvent]:
        return [e for e in self._events if e.correlation_id == correlation_id]

    def query_by_source(self, source: str) -> list[ControlEvent]:
        return [e for e in self._events if e.source == source]

    def query_by_type(self, event_type: str) -> list[ControlEvent]:
        return [e for e in self._events if e.event_type == event_type]

    def recent_events(self, limit: int = 100) -> list[ControlEvent]:
        return self._events[-limit:]

    def clear_events(self) -> None:
        self._events.clear()

    # -- Enforcement reporting ----------------------------------------------

    def report_enforcement(
        self, component: str, identity: str, level: EnforcementLevel
    ) -> None:
        reg = self._registry.get(f"{component}:{identity}")
        if reg is not None:
            reg.enforcement = level

    def get_enforcement(
        self, component: str, identity: str
    ) -> EnforcementLevel:
        reg = self._registry.get(f"{component}:{identity}")
        if reg is None:
            return EnforcementLevel.ADVISORY
        return reg.enforcement

    # -- Decision helpers ---------------------------------------------------

    def make_decision(
        self,
        verdict: str,
        *,
        reason: str,
        correlation_id: str | None = None,
        enforcement_level: EnforcementLevel = EnforcementLevel.ROUTED,
    ) -> ControlDecision:
        if verdict == "autonomous":
            return ControlDecision.autonomous(
                reason=reason, enforcement_level=enforcement_level,
                correlation_id=correlation_id or new_correlation_id(),
            )
        if verdict == "escalation_required":
            return ControlDecision.escalation(
                reason=reason, enforcement_level=enforcement_level,
                correlation_id=correlation_id or new_correlation_id(),
            )
        if verdict == "denied":
            return ControlDecision.denied(
                reason=reason, enforcement_level=enforcement_level,
                correlation_id=correlation_id or new_correlation_id(),
            )
        return ControlDecision.fail_closed(
            reason=reason or "fail closed: invalid verdict",
            correlation_id=correlation_id or new_correlation_id(),
        )

    def emit_decision(
        self,
        decision: ControlDecision,
        source: str = "kernel",
    ) -> ControlEvent:
        event_type_map = {
            "autonomous": "allowed",
            "escalation_required": "approval_requested",
            "denied": "denied",
        }
        etype = event_type_map.get(decision.verdict, "evaluated")
        event = ControlEvent(
            event_type=etype,
            correlation_id=decision.correlation_id,
            source=source,
            action_digest=decision.action_digest,
            enforcement_level=decision.enforcement_level,
            approval_semantics=decision.approval_semantics,
            timestamp=decision.timestamp,
            event_data=(),
        )
        return self.emit(event)
