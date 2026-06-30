"""Tests for the @govern decorator."""
import json
import tempfile
from pathlib import Path

import pytest

from custodian import govern, GovernedResult, EscalationRequired, KernelDenied


def test_govern_autonomous_within_cap():
    @govern(band="L2", cap=50.00)
    def charge(amount: float) -> dict:
        return {"ok": True, "amount": amount}

    result = charge(amount=10.00)
    assert result.ok
    assert result.verdict == "autonomous"
    assert result.value == {"ok": True, "amount": 10.00}
    assert isinstance(result.audit_id, str)
    assert result.elapsed_ms >= 0


def test_govern_escalation_raised_over_cap():
    @govern(band="L2", cap=5.00, raise_on_escalation=True)
    def big_charge(amount: float) -> dict:
        return {}

    with pytest.raises(EscalationRequired):
        big_charge(amount=100.00)


def test_govern_escalation_returned_no_raise():
    @govern(band="L2", cap=5.00, raise_on_escalation=False)
    def big_charge(amount: float) -> dict:
        return {}

    result = big_charge(amount=100.00)
    assert not result.ok
    assert result.verdict == "escalation_required"
    assert result.value is None


def test_govern_denied_on_kill_switch():
    with tempfile.TemporaryDirectory() as td:
        ks = Path(td) / "kill_switch.json"
        ks.write_text(json.dumps({"killed": True}))

        @govern(band="L2", cap=100.00, state_dir=td, raise_on_escalation=False)
        def charge(amount: float) -> dict:
            return {}

        result = charge(amount=10.00)
        assert result.verdict == "denied"
        assert not result.ok


def test_govern_denied_raises_kernel_denied():
    with tempfile.TemporaryDirectory() as td:
        ks = Path(td) / "kill_switch.json"
        ks.write_text(json.dumps({"killed": True}))

        @govern(band="L2", cap=100.00, state_dir=td, raise_on_escalation=True)
        def charge(amount: float) -> dict:
            return {}

        with pytest.raises(KernelDenied):
            charge(amount=10.00)


def test_governed_function_metadata():
    @govern(band="L3", cap=25.00)
    def do_something():
        return "done"

    assert do_something._governed is True
    assert do_something._band == "L3"
    assert do_something._cap == 25.00


def test_govern_result_receipt():
    @govern(band="L2", cap=50.00)
    def charge(amount: float) -> dict:
        return {"charged": amount}

    result = charge(amount=5.00)
    assert result.fn_name == "charge"
    receipt = result.receipt()
    assert receipt.verify()
    assert receipt.band == "L2"
    assert receipt.amount == 5.00
    assert receipt.fn_name == "charge"  # must record actual function name, not description


def test_govern_amount_from_kwarg():
    called_with = {}

    @govern(band="L2", cap=100.00)
    def do(amount: float, note: str = "") -> dict:
        called_with["amount"] = amount
        return {"done": True}

    result = do(amount=42.50, note="test")
    assert result.ok
    assert result.amount == 42.50


def test_govern_zero_cost_function():
    @govern(band="L0", cost_usd=0.0)
    def read_data() -> list:
        return [1, 2, 3]

    result = read_data()
    assert result.ok
    assert result.value == [1, 2, 3]
