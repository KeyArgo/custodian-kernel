"""Tests for the control-plane contracts (contracts.py) and
control-plane service (service.py).

Covers sanitised events, correlation-ID chains, consistent approval
semantics, enforcement-level reporting, and the single shared decision
gate — no adapter-specific competing gate.
"""
from __future__ import annotations

import time
from uuid import uuid4

import pytest

from custodian.control.contracts import (
    ApprovalSemantics,
    ControlDecision,
    ControlEvent,
    ControlEventSanitizer,
    EnforcementLevel,
    EnforcementReport,
    LIFECYCLE_TRANSITIONS,
    WELL_KNOWN_SOURCES,
    new_correlation_id,
)
from custodian.control.service import ControlService


# =========================================================================
# Correlation ID
# =========================================================================


class TestCorrelationId:
    def test_new_id_is_hex_string(self) -> None:
        cid = new_correlation_id()
        assert isinstance(cid, str)
        assert len(cid) == 32
        assert all(c in "0123456789abcdef" for c in cid)

    def test_ids_are_unique(self) -> None:
        ids = {new_correlation_id() for _ in range(100)}
        assert len(ids) == 100


# =========================================================================
# ControlEvent
# =========================================================================


class TestControlEvent:
    def test_valid_event(self) -> None:
        cid = new_correlation_id()
        e = ControlEvent(
            event_type="proposed",
            correlation_id=cid,
            source="codex",
            action_digest="abc123",
            enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        )
        assert e.event_type == "proposed"
        assert e.correlation_id == cid
        assert e.source == "codex"
        assert e.enforcement_level == EnforcementLevel.ROUTED
        assert e.approval_semantics == ApprovalSemantics.ASK

    def test_invalid_event_type_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown event_type"):
            ControlEvent(
                event_type="bogus",
                correlation_id=new_correlation_id(),
                source="codex",
                action_digest="d",
                enforcement_level=EnforcementLevel.ROUTED,
                approval_semantics=ApprovalSemantics.ASK,
            )

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown source"):
            ControlEvent(
                event_type="proposed",
                correlation_id=new_correlation_id(),
                source="alien",
                action_digest="d",
                enforcement_level=EnforcementLevel.ROUTED,
                approval_semantics=ApprovalSemantics.ASK,
            )

    @pytest.mark.parametrize("transition", sorted(LIFECYCLE_TRANSITIONS))
    def test_all_lifecycle_transitions_valid(self, transition: str) -> None:
        e = ControlEvent(
            event_type=transition,
            correlation_id=new_correlation_id(),
            source="kernel",
            action_digest="d",
            enforcement_level=EnforcementLevel.NATIVE,
            approval_semantics=ApprovalSemantics.DENY,
        )
        assert e.event_type == transition

    @pytest.mark.parametrize("source", sorted(WELL_KNOWN_SOURCES))
    def test_all_well_known_sources_valid(self, source: str) -> None:
        e = ControlEvent(
            event_type="proposed",
            correlation_id=new_correlation_id(),
            source=source,
            action_digest="d",
            enforcement_level=EnforcementLevel.BROKERED,
            approval_semantics=ApprovalSemantics.AUTO,
        )
        assert e.source == source

    def test_to_dict_omits_secrets(self) -> None:
        e = ControlEvent(
            event_type="proposed",
            correlation_id=new_correlation_id(),
            source="executor",
            action_digest="d",
            enforcement_level=EnforcementLevel.BROKERED,
            approval_semantics=ApprovalSemantics.ASK,
            event_data=frozenset([
                ("token", "sk_live_abc"),
                ("api_key", "12345"),
                ("safe_key", "visible"),
            ]),
        )
        d = e.to_dict()
        # Secret-bearing keys should be redacted
        assert d["event_data"]["token"] == "[REDACTED]"
        assert d["event_data"]["api_key"] == "[REDACTED]"
        # Non-secret keys survive
        assert d["event_data"]["safe_key"] == "visible"

    def test_to_dict_roundtrip(self) -> None:
        cid = new_correlation_id()
        e = ControlEvent(
            event_type="succeeded",
            correlation_id=cid,
            source="executor",
            action_digest="deadbeef",
            enforcement_level=EnforcementLevel.NATIVE,
            approval_semantics=ApprovalSemantics.AUTO,
            timestamp=1234.0,
        )
        d = e.to_dict()
        assert d["event_type"] == "succeeded"
        assert d["correlation_id"] == cid
        assert d["source"] == "executor"
        assert d["action_digest"] == "deadbeef"
        assert d["enforcement_level"] == "native"
        assert d["approval_semantics"] == "auto"
        assert d["timestamp"] == 1234.0


# =========================================================================
# ControlEventSanitizer
# =========================================================================


class TestControlEventSanitizer:
    def test_sanitize_strips_secrets(self) -> None:
        raw = {
            "token": "ghp_abc123",
            "api_key": "sk_live_secret",
            "normal_field": "hello",
            "nested": {"password": "s3cret", "visible": "ok"},
        }
        cleaned = ControlEventSanitizer.sanitize(raw)
        assert cleaned["token"] == "[REDACTED]"
        assert cleaned["api_key"] == "[REDACTED]"
        assert cleaned["normal_field"] == "hello"
        assert cleaned["nested"]["password"] == "[REDACTED]"
        assert cleaned["nested"]["visible"] == "ok"

    def test_sanitize_none_returns_empty(self) -> None:
        assert ControlEventSanitizer.sanitize(None) == {}

    def test_sanitize_empty_dict(self) -> None:
        assert ControlEventSanitizer.sanitize({}) == {}

    def test_sanitize_event_data_frozenset(self) -> None:
        raw = {"api_key": "sk_live_x", "name": "test"}
        fs = ControlEventSanitizer.sanitize_event_data(raw)
        d = dict(fs)
        assert d["api_key"] == "[REDACTED]"
        assert d["name"] == "test"

    def test_nested_event_data_is_supported(self) -> None:
        event_data = ControlEventSanitizer.sanitize_event_data({
            "nested": {"token": "secret", "safe": ["value"]},
        })
        assert dict(event_data)["nested"] == {"token": "[REDACTED]", "safe": ["value"]}


# =========================================================================
# EnforcementLevel
# =========================================================================


class TestEnforcementLevel:
    def test_strictest_is_native(self) -> None:
        assert EnforcementLevel.strictest() == EnforcementLevel.NATIVE

    @pytest.mark.parametrize("level,expected", [
        (EnforcementLevel.ADVISORY, False),
        (EnforcementLevel.ROUTED, False),
        (EnforcementLevel.BROKERED, True),
        (EnforcementLevel.NATIVE, True),
    ])
    def test_cannot_bypass(self, level: EnforcementLevel, expected: bool) -> None:
        assert level.cannot_bypass() == expected

    def test_order_is_stable(self) -> None:
        levels = list(EnforcementLevel)
        assert levels == [
            EnforcementLevel.ADVISORY,
            EnforcementLevel.ROUTED,
            EnforcementLevel.BROKERED,
            EnforcementLevel.NATIVE,
        ]


# =========================================================================
# ApprovalSemantics
# =========================================================================


class TestApprovalSemantics:
    @pytest.mark.parametrize("sem,expected", [
        (ApprovalSemantics.DENY, False),
        (ApprovalSemantics.ASK, True),
        (ApprovalSemantics.AUTO, False),
    ])
    def test_requires_human(self, sem: ApprovalSemantics, expected: bool) -> None:
        assert sem.requires_human() == expected

    @pytest.mark.parametrize("sem,expected", [
        (ApprovalSemantics.DENY, False),
        (ApprovalSemantics.ASK, True),
        (ApprovalSemantics.AUTO, True),
    ])
    def test_is_governed(self, sem: ApprovalSemantics, expected: bool) -> None:
        assert sem.is_governed() == expected


# =========================================================================
# ControlDecision  — the single shared gate
# =========================================================================


class TestControlDecision:
    def test_autonomous_factory(self) -> None:
        d = ControlDecision.autonomous(reason="within cap")
        assert d.verdict == "autonomous"
        assert d.reason == "within cap"
        assert d.approval_semantics == ApprovalSemantics.AUTO
        assert d.is_allowed
        assert not d.is_denied
        assert not d.is_escalated

    def test_escalation_factory(self) -> None:
        d = ControlDecision.escalation(reason="over cap")
        assert d.verdict == "escalation_required"
        assert d.reason == "over cap"
        assert d.approval_semantics == ApprovalSemantics.ASK
        assert not d.is_allowed
        assert d.is_escalated

    def test_denied_factory(self) -> None:
        d = ControlDecision.denied(reason="kill switch")
        assert d.verdict == "denied"
        assert d.reason == "kill switch"
        assert d.approval_semantics == ApprovalSemantics.DENY
        assert not d.is_allowed
        assert d.is_denied

    def test_fail_closed_on_invalid(self) -> None:
        d = ControlDecision.fail_closed(reason="unexpected state")
        assert d.verdict == "denied"
        assert d.reason == "unexpected state"
        assert d.enforcement_level == EnforcementLevel.NATIVE

    def test_fail_closed_default_reason(self) -> None:
        d = ControlDecision.fail_closed()
        assert d.verdict == "denied"
        assert "fail closed" in d.reason

    def test_invalid_verdict_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown verdict"):
            ControlDecision(
                verdict="maybe",
                reason="bogus",
                enforcement_level=EnforcementLevel.ROUTED,
                approval_semantics=ApprovalSemantics.ASK,
            )

    def test_to_dict_contains_all_fields(self) -> None:
        cid = new_correlation_id()
        d = ControlDecision(
            verdict="autonomous",
            reason="within band",
            enforcement_level=EnforcementLevel.BROKERED,
            approval_semantics=ApprovalSemantics.AUTO,
            correlation_id=cid,
            action_digest="feedface",
            timestamp=5678.0,
        )
        dumped = d.to_dict()
        assert dumped["verdict"] == "autonomous"
        assert dumped["reason"] == "within band"
        assert dumped["enforcement_level"] == "brokered"
        assert dumped["approval_semantics"] == "auto"
        assert dumped["correlation_id"] == cid
        assert dumped["action_digest"] == "feedface"
        assert dumped["timestamp"] == 5678.0

    def test_decision_carries_correlation_id(self) -> None:
        cid = new_correlation_id()
        d = ControlDecision(
            verdict="denied",
            reason="no",
            enforcement_level=EnforcementLevel.NATIVE,
            approval_semantics=ApprovalSemantics.DENY,
            correlation_id=cid,
        )
        assert d.correlation_id == cid


# =========================================================================
# EnforcementReport
# =========================================================================


class TestEnforcementReport:
    def test_from_decision_autonomous(self) -> None:
        d = ControlDecision.autonomous(reason="ok")
        report = EnforcementReport.from_decision(
            adapter="test-adapter", source="codex", decision=d,
        )
        assert report.adapter == "test-adapter"
        assert report.source == "codex"
        assert report.correlation_id == d.correlation_id
        assert report.outcome == "allowed"
        assert report.declared_level == EnforcementLevel.ROUTED
        assert report.enforced_as == EnforcementLevel.ROUTED

    def test_from_decision_escalation(self) -> None:
        d = ControlDecision.escalation(reason="needs human")
        report = EnforcementReport.from_decision(
            adapter="test", source="executor", decision=d,
        )
        assert report.outcome == "escalated"

    def test_from_decision_denied(self) -> None:
        d = ControlDecision.denied(reason="blocked")
        report = EnforcementReport.from_decision(
            adapter="test", source="paladin", decision=d,
        )
        assert report.outcome == "denied"

    def test_to_dict(self) -> None:
        d = ControlDecision.autonomous(reason="ok")
        report = EnforcementReport.from_decision(
            adapter="a", source="s", decision=d,
        )
        dumped = report.to_dict()
        assert dumped["adapter"] == "a"
        assert dumped["source"] == "s"
        assert dumped["outcome"] == "allowed"


# =========================================================================
# ControlService  — orchestrator
# =========================================================================


class TestControlService:
    # -- Component registration --------------------------------------------

    def test_register_and_list(self) -> None:
        svc = ControlService()
        reg = svc.register("codex", "instance-1", EnforcementLevel.ROUTED)
        assert reg.component == "codex"
        assert reg.identity == "instance-1"
        assert reg.enforcement == EnforcementLevel.ROUTED
        assert reg.healthy

        listing = svc.list_components()
        assert len(listing) == 1
        assert listing[0].component == "codex"

    def test_register_multiple_components(self) -> None:
        svc = ControlService()
        svc.register("codex", "a")
        svc.register("talaria", "b")
        svc.register("paladin", "c")
        svc.register("executor", "d")
        assert len(svc.list_components()) == 4

    def test_get_component(self) -> None:
        svc = ControlService()
        svc.register("codex", "x", EnforcementLevel.BROKERED)
        reg = svc.get_component("codex", "x")
        assert reg is not None
        assert reg.enforcement == EnforcementLevel.BROKERED

    def test_get_component_nonexistent(self) -> None:
        svc = ControlService()
        assert svc.get_component("ghost", "x") is None

    def test_unregister(self) -> None:
        svc = ControlService()
        svc.register("codex", "a")
        assert svc.unregister("codex", "a") is True
        assert svc.get_component("codex", "a") is None
        assert len(svc.list_components()) == 0

    def test_unregister_nonexistent(self) -> None:
        svc = ControlService()
        assert svc.unregister("ghost", "x") is False

    def test_heartbeat_updates_last_seen(self) -> None:
        svc = ControlService()
        svc.register("codex", "a")
        before = svc.get_component("codex", "a")
        assert before is not None
        before_last = before.last_seen
        time.sleep(0.001)
        svc.heartbeat("codex", "a")
        after = svc.get_component("codex", "a")
        assert after is not None
        assert after.last_seen > before_last
        assert after.healthy is True

    # -- Events ------------------------------------------------------------

    def test_emit_event(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()
        e = ControlEvent(
            event_type="proposed",
            correlation_id=cid,
            source="codex",
            action_digest="dead",
            enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        )
        returned = svc.emit(e)
        assert returned.event_type == "proposed"
        assert returned.correlation_id == cid

    def test_query_by_correlation(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()
        e1 = ControlEvent(
            event_type="proposed", correlation_id=cid, source="codex",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        )
        e2 = ControlEvent(
            event_type="allowed", correlation_id=cid, source="kernel",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.AUTO,
        )
        svc.emit(e1)
        svc.emit(e2)
        events = svc.query_by_correlation(cid)
        assert len(events) == 2

    def test_query_by_source(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()
        svc.emit(ControlEvent(
            event_type="proposed", correlation_id=cid, source="codex",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        ))
        svc.emit(ControlEvent(
            event_type="evaluated", correlation_id=cid, source="kernel",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        ))
        svc.emit(ControlEvent(
            event_type="allowed", correlation_id=cid, source="kernel",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.AUTO,
        ))
        assert len(svc.query_by_source("codex")) == 1
        assert len(svc.query_by_source("kernel")) == 2

    def test_query_by_type(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()
        svc.emit(ControlEvent(
            event_type="proposed", correlation_id=cid, source="codex",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        ))
        svc.emit(ControlEvent(
            event_type="allowed", correlation_id=cid, source="kernel",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.AUTO,
        ))
        assert len(svc.query_by_type("proposed")) == 1
        assert len(svc.query_by_type("allowed")) == 1
        assert len(svc.query_by_type("denied")) == 0

    def test_recent_events_respects_limit(self) -> None:
        svc = ControlService(max_events=3)
        cid = new_correlation_id()
        for i in range(5):
            svc.emit(ControlEvent(
                event_type="proposed", correlation_id=cid, source="codex",
                action_digest=f"{i}", enforcement_level=EnforcementLevel.ROUTED,
                approval_semantics=ApprovalSemantics.ASK,
            ))
        assert len(svc.recent_events(100)) == 3

    def test_clear_events(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()
        svc.emit(ControlEvent(
            event_type="proposed", correlation_id=cid, source="codex",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        ))
        assert len(svc.recent_events(10)) == 1
        svc.clear_events()
        assert len(svc.recent_events(10)) == 0

    def test_correlation_chain_returns_chronological(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()
        svc.emit(ControlEvent(
            event_type="proposed", correlation_id=cid, source="codex",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        ))
        svc.emit(ControlEvent(
            event_type="evaluated", correlation_id=cid, source="kernel",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        ))
        svc.emit(ControlEvent(
            event_type="allowed", correlation_id=cid, source="kernel",
            action_digest="a", enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.AUTO,
        ))
        chain = svc.query_by_correlation(cid)
        types = [e.event_type for e in chain]
        assert types == ["proposed", "evaluated", "allowed"]

    # -- Enforcement reporting ---------------------------------------------

    def test_report_and_get_enforcement(self) -> None:
        svc = ControlService()
        svc.register("codex", "a", EnforcementLevel.ADVISORY)
        svc.report_enforcement("codex", "a", EnforcementLevel.BROKERED)
        assert svc.get_enforcement("codex", "a") == EnforcementLevel.BROKERED

    def test_get_enforcement_unregistered_returns_advisory(self) -> None:
        svc = ControlService()
        assert svc.get_enforcement("ghost", "x") == EnforcementLevel.ADVISORY

    # -- Decision helpers --------------------------------------------------

    def test_make_decision_autonomous(self) -> None:
        svc = ControlService()
        d = svc.make_decision("autonomous", reason="ok")
        assert d.verdict == "autonomous"
        assert d.reason == "ok"
        assert isinstance(d.correlation_id, str)
        assert len(d.correlation_id) == 32

    def test_make_decision_escalation(self) -> None:
        svc = ControlService()
        d = svc.make_decision("escalation_required", reason="over cap")
        assert d.verdict == "escalation_required"

    def test_make_decision_denied(self) -> None:
        svc = ControlService()
        d = svc.make_decision("denied", reason="kill switch")
        assert d.verdict == "denied"

    def test_make_decision_preserves_correlation_id(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()
        d = svc.make_decision("denied", reason="no", correlation_id=cid)
        assert d.correlation_id == cid

    def test_make_decision_with_enforcement_level(self) -> None:
        svc = ControlService()
        d = svc.make_decision(
            "denied", reason="no",
            enforcement_level=EnforcementLevel.NATIVE,
        )
        assert d.enforcement_level == EnforcementLevel.NATIVE

    def test_emit_decision_produces_event(self) -> None:
        svc = ControlService()
        d = svc.make_decision("autonomous", reason="within cap")
        event = svc.emit_decision(d, source="executor")
        assert event.event_type == "allowed"
        assert event.source == "executor"
        assert event.correlation_id == d.correlation_id

    def test_emit_decision_escalation_event_type(self) -> None:
        svc = ControlService()
        d = svc.make_decision("escalation_required", reason="needs human")
        event = svc.emit_decision(d)
        assert event.event_type == "approval_requested"

    def test_emit_decision_denied_event_type(self) -> None:
        svc = ControlService()
        d = svc.make_decision("denied", reason="no")
        event = svc.emit_decision(d)
        assert event.event_type == "denied"

    def test_emit_decision_stores_in_event_log(self) -> None:
        svc = ControlService()
        d = svc.make_decision("autonomous", reason="ok")
        svc.emit_decision(d, source="codex")
        assert len(svc.recent_events(10)) == 1


# =========================================================================
# Cross-component integration scenario
# =========================================================================


class TestCrossComponentFlow:
    """Simulate a real multi-component lifecycle through the shared gate."""

    def test_full_lifecycle_via_correlation_chain(self) -> None:
        svc = ControlService()
        cid = new_correlation_id()

        # Codex proposes
        svc.emit(ControlEvent(
            event_type="proposed",
            correlation_id=cid,
            source="codex",
            action_digest="deadbeef",
            enforcement_level=EnforcementLevel.ROUTED,
            approval_semantics=ApprovalSemantics.ASK,
        ))

        # Kernel evaluates
        d = svc.make_decision("autonomous", reason="within L1 band",
                              correlation_id=cid)
        svc.emit_decision(d, source="kernel")

        # Executor starts and succeeds
        svc.emit(ControlEvent(
            event_type="execution_started",
            correlation_id=cid,
            source="executor",
            action_digest="deadbeef",
            enforcement_level=EnforcementLevel.BROKERED,
            approval_semantics=ApprovalSemantics.AUTO,
        ))
        svc.emit(ControlEvent(
            event_type="succeeded",
            correlation_id=cid,
            source="executor",
            action_digest="deadbeef",
            enforcement_level=EnforcementLevel.BROKERED,
            approval_semantics=ApprovalSemantics.AUTO,
        ))

        chain = svc.query_by_correlation(cid)
        types = [e.event_type for e in chain]
        assert types == [
            "proposed",
            "allowed",
            "execution_started",
            "succeeded",
        ]

    def test_component_registration_across_sources(self) -> None:
        svc = ControlService()
        svc.register("codex", "build-1", EnforcementLevel.ROUTED)
        svc.register("talaria", "hermes-prod", EnforcementLevel.BROKERED)
        svc.register("paladin", "vault-main", EnforcementLevel.NATIVE)
        svc.register("executor", "exec-1", EnforcementLevel.BROKERED)

        assert svc.get_enforcement("codex", "build-1") == EnforcementLevel.ROUTED
        assert svc.get_enforcement("talaria", "hermes-prod") == EnforcementLevel.BROKERED
        assert svc.get_enforcement("paladin", "vault-main") == EnforcementLevel.NATIVE
        assert svc.get_enforcement("executor", "exec-1") == EnforcementLevel.BROKERED

        # Unregistered component gets advisory (fail-closed default)
        assert svc.get_enforcement("ghost", "x") == EnforcementLevel.ADVISORY

    def test_multi_source_same_correlation(self) -> None:
        """All four well-known sources emit events for one action."""
        svc = ControlService()
        cid = new_correlation_id()

        sources = ["codex", "hermes", "paladin", "executor"]
        for src in sources:
            svc.emit(ControlEvent(
                event_type="evaluated", correlation_id=cid, source=src,
                action_digest="d", enforcement_level=EnforcementLevel.ROUTED,
                approval_semantics=ApprovalSemantics.ASK,
            ))

        events = svc.query_by_correlation(cid)
        emitted_sources = {e.source for e in events}
        assert emitted_sources == set(sources)

    def test_decision_shared_across_components(self) -> None:
        """All four components consume the same ControlDecision shape."""
        svc = ControlService()
        cid = new_correlation_id()

        d = ControlDecision(
            verdict="denied",
            reason="test: all adapters share this gate",
            enforcement_level=EnforcementLevel.BROKERED,
            approval_semantics=ApprovalSemantics.DENY,
            correlation_id=cid,
        )

        # Every component reports via the same decision
        event = svc.emit_decision(d, source="kernel")
        assert event.correlation_id == cid
        assert event.event_type == "denied"

        # Enforcement report also consumes the same decision
        report = EnforcementReport.from_decision(
            adapter="codex", source="codex", decision=d,
        )
        assert report.outcome == "denied"
        assert report.correlation_id == cid

    def test_fail_closed_unregistered_enforcement(self) -> None:
        """An unknown component gets the weakest enforcement (advisory)
        by default — fail closed rather than crash or return None."""
        svc = ControlService()
        assert svc.get_enforcement("unknown", "x") == EnforcementLevel.ADVISORY

    def test_fail_closed_invalid_verdict_in_make_decision(self) -> None:
        """make_decision fail-closes on invalid verdict instead of raising."""
        svc = ControlService()
        d = svc.make_decision("bogus", reason="should not exist")
        assert d.verdict == "denied"
        assert d.approval_semantics == ApprovalSemantics.DENY
        assert d.enforcement_level == EnforcementLevel.NATIVE
