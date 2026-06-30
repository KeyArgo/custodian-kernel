"""
Stress tests for the Custodian 0.2.0 kernel.

Covers: concurrency, amount edge cases, kill-switch file corruption (fail-closed),
receipt integrity at scale, exception propagation, sub-session depth, EventBus
under load, and policy/state file fallback paths.
"""
from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import pytest

from custodian import govern, EscalationRequired, KernelDenied
from custodian.bus import EventBus
from custodian.receipt import GovernedReceipt
from custodian.session import CustodianSession


# ---------------------------------------------------------------------------
# @govern — amount edge cases
# ---------------------------------------------------------------------------

class TestGoverAmountEdgeCases:
    def test_amount_zero_treated_as_autonomous(self):
        @govern(band="L2", cap=10.00)
        def noop() -> dict:
            return {"ok": True}

        result = noop()
        assert result.ok
        assert result.amount == 0.0

    def test_large_amount_escalates(self):
        @govern(band="L2", cap=5.00, raise_on_escalation=False)
        def big(amount: float) -> dict:
            return {}

        result = big(amount=1_000_000.00)
        assert result.verdict == "escalation_required"
        assert result.amount == 1_000_000.00

    def test_negative_amount_in_kwarg(self):
        """Negative amount should not trip the positional arg scanner (it's > 0 check)."""
        @govern(band="L2", cap=10.00)
        def refund(amount: float) -> dict:
            return {"refunded": amount}

        result = refund(amount=-5.00)
        assert result.amount == -5.00
        assert result.ok  # negative amount < cap, should be autonomous

    def test_float_precision_amount(self):
        @govern(band="L2", cap=10.00)
        def micro(amount: float) -> dict:
            return {}

        result = micro(amount=0.001)
        assert result.ok
        assert result.amount == pytest.approx(0.001)

    def test_cost_usd_blocks_positional_amount_detection(self):
        """When cost_usd is set and amount not in kwargs, positional arg is ignored."""
        calls_with = []

        @govern(band="L2", cap=100.00, cost_usd=1.00)
        def fn(real_amount: float) -> dict:
            calls_with.append(real_amount)
            return {}

        result = fn(50.00)  # positional — but cost_usd=1.00 wins
        assert result.amount == pytest.approx(1.00)  # documented behaviour: cost_usd takes precedence
        assert calls_with == [50.00]  # function still gets the real arg

    def test_amount_kwarg_overrides_cost_usd(self):
        @govern(band="L2", cap=100.00, cost_usd=1.00)
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=75.00)  # explicit kwarg wins over cost_usd
        assert result.amount == pytest.approx(75.00)


# ---------------------------------------------------------------------------
# @govern — exception propagation
# ---------------------------------------------------------------------------

class TestGovernExceptionPropagation:
    def test_exception_in_governed_function_propagates(self):
        @govern(band="L2", cap=100.00)
        def boom(amount: float) -> dict:
            raise ValueError("something went wrong")

        with pytest.raises(ValueError, match="something went wrong"):
            boom(amount=5.00)

    def test_exception_not_swallowed_by_eventbus(self):
        """An exception in the governed fn must not be masked by post_execute bus emit."""
        @govern(band="L2", cap=100.00)
        def explode(amount: float) -> dict:
            raise RuntimeError("kaboom")

        with pytest.raises(RuntimeError, match="kaboom"):
            explode(amount=1.00)

    def test_raise_on_escalation_false_returns_result_for_denial(self, tmp_path):
        """raise_on_escalation=False should return GovernedResult instead of raising for both denial and escalation."""
        ks = tmp_path / "kill_switch.json"
        ks.write_text(json.dumps({"killed": True}))

        @govern(band="L2", cap=50.00, state_dir=str(tmp_path), raise_on_escalation=False)
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=5.00)
        assert result.verdict == "denied"
        assert not result.ok
        assert result.fn_name == "fn"

    def test_raise_on_escalation_true_raises_kernel_denied_when_killed(self, tmp_path):
        ks = tmp_path / "kill_switch.json"
        ks.write_text(json.dumps({"killed": True}))

        @govern(band="L2", cap=50.00, state_dir=str(tmp_path), raise_on_escalation=True)
        def fn(amount: float) -> dict:
            return {}

        with pytest.raises(KernelDenied):
            fn(amount=5.00)


# ---------------------------------------------------------------------------
# @govern — fn_name stored and propagated correctly
# ---------------------------------------------------------------------------

class TestGovernFnName:
    def test_fn_name_on_autonomous_result(self):
        @govern(band="L2", cap=50.00)
        def my_function(amount: float) -> dict:
            return {}

        result = my_function(amount=1.00)
        assert result.fn_name == "my_function"

    def test_fn_name_on_escalated_result(self):
        @govern(band="L2", cap=1.00, raise_on_escalation=False)
        def another_fn(amount: float) -> dict:
            return {}

        result = another_fn(amount=999.00)
        assert result.fn_name == "another_fn"
        assert result.verdict == "escalation_required"

    def test_fn_name_preserved_in_receipt(self):
        @govern(band="L2", cap=50.00)
        def charge_customer(amount: float) -> dict:
            return {"charged": amount}

        result = charge_customer(amount=10.00)
        receipt = result.receipt()
        assert receipt.fn_name == "charge_customer"
        assert receipt.verify()

    def test_fn_name_not_overwritten_by_description(self):
        @govern(band="L2", cap=50.00, description="A custom description")
        def process_payment(amount: float) -> dict:
            return {}

        result = process_payment(amount=5.00)
        assert result.fn_name == "process_payment"  # not "A custom description"
        assert result.description == "A custom description"
        receipt = result.receipt()
        assert receipt.fn_name == "process_payment"
        assert receipt.description == "A custom description"


# ---------------------------------------------------------------------------
# Kill switch — file corruption (fail-closed fix)
# ---------------------------------------------------------------------------

class TestKillSwitchFileFaultTolerance:
    def test_corrupted_kill_switch_fails_closed(self, tmp_path):
        """Corrupted kill_switch.json must be treated as killed=True (fail-closed)."""
        ks = tmp_path / "kill_switch.json"
        ks.write_bytes(b"\x00\xff\xfe invalid binary garbage")

        @govern(band="L2", cap=50.00, state_dir=str(tmp_path), raise_on_escalation=False)
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=5.00)
        assert result.verdict == "denied"

    def test_empty_kill_switch_file_fails_closed(self, tmp_path):
        ks = tmp_path / "kill_switch.json"
        ks.write_text("")

        @govern(band="L2", cap=50.00, state_dir=str(tmp_path), raise_on_escalation=False)
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=5.00)
        assert result.verdict == "denied"

    def test_valid_kill_switch_not_killed(self, tmp_path):
        ks = tmp_path / "kill_switch.json"
        ks.write_text(json.dumps({"killed": False}))

        @govern(band="L2", cap=50.00, state_dir=str(tmp_path))
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=5.00)
        assert result.verdict == "autonomous"

    def test_truncated_json_fails_closed(self, tmp_path):
        ks = tmp_path / "kill_switch.json"
        ks.write_text('{"killed": tru')  # truncated

        @govern(band="L2", cap=50.00, state_dir=str(tmp_path), raise_on_escalation=False)
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=5.00)
        assert result.verdict == "denied"

    def test_kill_switch_absent_means_not_killed(self, tmp_path):
        """No kill_switch.json at all should default to not killed."""
        @govern(band="L2", cap=50.00, state_dir=str(tmp_path))
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=5.00)
        assert result.verdict == "autonomous"


# ---------------------------------------------------------------------------
# Receipt — integrity at scale + JSON round-trip
# ---------------------------------------------------------------------------

class TestReceiptAtScale:
    def test_1000_receipts_all_verify(self):
        receipts = [
            GovernedReceipt.build(
                fn_name=f"fn_{i}", band="L2", amount=float(i % 50),
                description=f"desc_{i}", verdict="autonomous",
                reason="ok", elapsed_ms=float(i), output={"i": i},
            )
            for i in range(1000)
        ]
        assert all(r.verify() for r in receipts)

    def test_receipt_ids_unique_across_1000(self):
        receipts = [
            GovernedReceipt.build(
                fn_name="fn", band="L2", amount=1.00,
                description="d", verdict="autonomous",
                reason="ok", elapsed_ms=0.0, output={},
            )
            for _ in range(1000)
        ]
        ids = {r.receipt_id for r in receipts}
        assert len(ids) == 1000

    def test_json_round_trip_verify(self):
        receipt = GovernedReceipt.build(
            fn_name="my_fn", band="L3", amount=99.99,
            description="big charge", verdict="autonomous",
            reason="within cap", elapsed_ms=42.0, output={"status": "ok"},
        )
        raw = json.loads(receipt.to_json())
        restored = GovernedReceipt(**raw)
        assert restored.verify()
        assert restored.fn_name == "my_fn"
        assert restored.amount == pytest.approx(99.99)

    def test_tamper_any_fingerprint_field_fails_verify(self):
        fields_and_values = [
            ("receipt_id", "00000000-fake-fake-fake-000000000000"),
            ("band", "L0"),
            ("amount", 0.01),
            ("verdict", "denied"),
            ("output_hash", "a" * 64),
        ]
        for field, bad_value in fields_and_values:
            receipt = GovernedReceipt.build(
                fn_name="fn", band="L2", amount=10.00,
                description="d", verdict="autonomous",
                reason="ok", elapsed_ms=0.0, output={"x": 1},
            )
            object.__setattr__(receipt, field, bad_value)
            assert not receipt.verify(), f"Expected verify() to fail after tampering {field}"

    def test_non_fingerprinted_fields_do_not_affect_verify(self):
        """Fields outside the fingerprint (ts, description, reason, elapsed_ms, fn_name)
        can be altered without breaking verify() — by design."""
        receipt = GovernedReceipt.build(
            fn_name="fn", band="L2", amount=10.00,
            description="d", verdict="autonomous",
            reason="ok", elapsed_ms=0.0, output={},
        )
        object.__setattr__(receipt, "ts", 0.0)
        object.__setattr__(receipt, "description", "TAMPERED")
        object.__setattr__(receipt, "reason", "TAMPERED")
        object.__setattr__(receipt, "elapsed_ms", 9999.9)
        object.__setattr__(receipt, "fn_name", "TAMPERED")
        assert receipt.verify()  # these fields are outside the fingerprint scope

    def test_output_hash_is_deterministic_for_complex_output(self):
        output = {"nested": {"a": 1, "b": [2, 3]}, "z": "last"}
        r1 = GovernedReceipt.build(
            fn_name="fn", band="L2", amount=1.00,
            description="d", verdict="autonomous",
            reason="ok", elapsed_ms=0.0, output=output,
        )
        r2 = GovernedReceipt.build(
            fn_name="fn", band="L2", amount=1.00,
            description="d", verdict="autonomous",
            reason="ok", elapsed_ms=0.0, output=output,
        )
        assert r1.output_hash == r2.output_hash


# ---------------------------------------------------------------------------
# CustodianSession — sub-session edge cases
# ---------------------------------------------------------------------------

class TestSubSessionEdgeCases:
    def test_sub_session_cap_zero_not_treated_as_falsy(self):
        """cap=0.0 on sub_session should use 0.0, not inherit parent cap."""
        with CustodianSession(band="L2", cap=100.00) as parent:
            child = parent.sub_session(band="L2", cap=0.0)
            r = child.request(amount=0.001)  # even tiny amount should escalate with cap=0
        assert r.verdict == "escalation_required"

    def test_sub_session_inherits_parent_policy_path(self, tmp_path):
        """sub_session must propagate parent's policy_path and state_dir."""
        with CustodianSession(band="L2", cap=50.00,
                               policy_path="/tmp/nonexistent.yaml",
                               state_dir=str(tmp_path)) as parent:
            child = parent.sub_session(band="L2")
        assert child.policy_path == "/tmp/nonexistent.yaml"
        assert child.state_dir == str(tmp_path)

    def test_sub_session_inherits_parent_state_dir(self, tmp_path):
        with CustodianSession(band="L2", cap=50.00, state_dir=str(tmp_path)) as parent:
            child = parent.sub_session(band="L2")
        assert child.state_dir == str(tmp_path)

    def test_deep_nested_sub_sessions_band_enforcement(self):
        """Nested L1→L2 sub-session should still be denied."""
        with CustodianSession(band="L1", cap=100.00) as l1:
            l2 = l1.sub_session(band="L2")
            r = l2.request(amount=1.00)
        assert r.verdict == "denied"
        assert "exceeds parent ceiling" in r.reason

    def test_five_level_deep_sub_session(self):
        """Five levels of nesting should not crash."""
        with CustodianSession(band="L2", cap=50.00) as s1:
            s2 = s1.sub_session(band="L2", cap=50.00)
            s3 = s2.sub_session(band="L2", cap=50.00)
            s4 = s3.sub_session(band="L2", cap=50.00)
            s5 = s4.sub_session(band="L2", cap=50.00)
            r = s5.request(amount=5.00)
        assert r.ok

    def test_sub_session_spent_propagates_to_all_ancestors(self):
        with CustodianSession(band="L2", cap=100.00) as grandparent:
            parent = grandparent.sub_session(band="L2", cap=100.00)
            child = parent.sub_session(band="L2", cap=100.00)
            child.request(amount=10.00)
        assert parent._spent == pytest.approx(10.00)
        assert grandparent._spent == pytest.approx(10.00)

    def test_summary_counts_all_verdicts(self):
        with CustodianSession(band="L2", cap=10.00) as session:
            session.request(amount=5.00)        # autonomous
            session.request(amount=5.00)        # autonomous
            session.request(amount=100.00)      # escalated
        s = session.summary()
        assert s["total"] == 3
        assert s["autonomous"] == 2
        assert s["escalated"] == 1
        assert s["denied"] == 0
        assert s["spent_usd"] == pytest.approx(10.00)


# ---------------------------------------------------------------------------
# EventBus — concurrent emit, handler isolation, scale
# ---------------------------------------------------------------------------

class TestEventBusStress:
    def test_concurrent_emit_50_threads(self):
        bus = EventBus()
        results = []
        lock = threading.Lock()

        @bus.on("work")
        def accumulate(p):
            with lock:
                results.append(p)

        threads = [threading.Thread(target=bus.emit, args=("work", i)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 50
        assert sorted(results) == list(range(50))

    def test_100_handlers_all_called(self):
        bus = EventBus()
        hits = []

        for i in range(100):
            def make_handler(n):
                def h(p): hits.append(n)
                h.__name__ = f"h_{n}"
                return h
            bus.on("mass")(make_handler(i))

        bus.emit("mass", None)
        assert len(hits) == 100

    def test_one_crashing_handler_doesnt_block_others(self):
        bus = EventBus()
        safe_calls = []

        @bus.on("ev")
        def crash(p):
            raise RuntimeError("I always crash")

        @bus.on("ev")
        def safe(p):
            safe_calls.append(p)

        bus.emit("ev", "payload")
        assert safe_calls == ["payload"]

    def test_emit_with_none_payload_does_not_crash(self):
        bus = EventBus()
        received = []

        @bus.on("ev")
        def h(p): received.append(p)

        bus.emit("ev")
        assert received == [None]

    def test_emit_to_unknown_event_is_silent(self):
        bus = EventBus()
        bus.emit("no_such_event", {"data": 1})  # must not raise


# ---------------------------------------------------------------------------
# Concurrent @govern calls (thread safety of decorator)
# ---------------------------------------------------------------------------

class TestConcurrentGovern:
    def test_100_concurrent_govern_calls(self):
        """@govern must be thread-safe: all 100 calls should return correct results."""
        @govern(band="L2", cap=50.00)
        def parallel_charge(amount: float) -> dict:
            time.sleep(0.001)  # simulate tiny I/O
            return {"amount": amount}

        results = []
        errors = []
        lock = threading.Lock()

        def worker(amount):
            try:
                r = parallel_charge(amount=amount)
                with lock:
                    results.append(r)
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(float(i % 10),)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Unexpected errors: {errors}"
        assert len(results) == 100
        assert all(r.ok for r in results)

    def test_concurrent_session_spent_tracking(self):
        """_spent must accumulate correctly across concurrent session.request() calls."""
        with CustodianSession(band="L2", cap=100.00) as session:
            barrier = threading.Barrier(10)

            def worker():
                barrier.wait()
                session.request(amount=1.00)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert session._spent == pytest.approx(10.00)
        assert session.summary()["autonomous"] == 10


# ---------------------------------------------------------------------------
# Policy / state file fallback paths
# ---------------------------------------------------------------------------

class TestPolicyStateFallback:
    def test_corrupted_authority_json_falls_back_to_decorator_cap(self, tmp_path):
        """Corrupted authority.json should fall back to the decorator's own cap."""
        auth = tmp_path / "authority.json"
        auth.write_bytes(b"\x00\xff corrupted")

        @govern(band="L2", cap=50.00, state_dir=str(tmp_path))
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=10.00)
        # With fallback state using cap=50.00, a $10 charge is autonomous
        assert result.verdict == "autonomous"

    def test_missing_state_dir_uses_config_default(self):
        """No state_dir on decorator should not crash — config default is used."""
        @govern(band="L2", cap=50.00)
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=1.00)
        assert result.ok

    def test_nonexistent_policy_path_falls_back_to_minimal(self, tmp_path):
        @govern(band="L2", cap=50.00, policy_path=str(tmp_path / "nonexistent.yaml"))
        def fn(amount: float) -> dict:
            return {}

        result = fn(amount=10.00)
        assert result.ok


# ---------------------------------------------------------------------------
# Audit log written by default bus handler
# ---------------------------------------------------------------------------

class TestAuditLogWritten:
    def test_govern_call_writes_to_bus_events_log(self, tmp_path, monkeypatch):
        """The default audit handler should write events to ~/.custodian/bus_events.log."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        @govern(band="L2", cap=50.00)
        def fn(amount: float) -> dict:
            return {"ok": True}

        fn(amount=5.00)

        log_path = fake_home / ".custodian" / "bus_events.log"
        assert log_path.exists(), "bus_events.log should be created automatically"
        content = log_path.read_text()
        assert "pre_execute" in content
        assert "post_execute" in content
