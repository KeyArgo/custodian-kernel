"""Tests for the vendor-neutral payment processor interface and its reference
implementation.

``base.py`` must stay importable with zero vendor dependencies, and
``ManualLedgerProcessor`` must behave like a real (if trivial) processor so the
kernel's authority/spend gate can be exercised end-to-end without any payment
vendor installed. Everything here is in-memory; nothing touches the network.
"""
from __future__ import annotations

import types
from typing import get_type_hints

import pytest

from custodian.processors.base import ChargeStatus, PaymentProcessor
from custodian.processors.manual import ManualLedgerProcessor


def test_manual_processor_satisfies_protocol_members() -> None:
    # Structural check that the reference implementation really implements the
    # interface: same attribute names, same method signatures. isinstance()
    # can't be used because PaymentProcessor is a plain Protocol (not
    # @runtime_checkable), so check the members directly.
    annotations = {
        k: v for k, v in get_type_hints(PaymentProcessor).items()
        if not k.startswith("_")
    }
    for name, hint in annotations.items():
        assert hasattr(ManualLedgerProcessor, name), (
            f"ManualLedgerProcessor is missing protocol member {name!r}"
        )
        if isinstance(hint, types.FunctionType):
            cls_attr = getattr(ManualLedgerProcessor, name)
            assert callable(cls_attr), f"protocol member {name!r} must be callable"
    # The four operation methods and two attributes from the protocol.
    for member in ("charge", "refund", "payout", "balance", "name", "minimum_charge"):
        assert hasattr(ManualLedgerProcessor, member)


def test_charge_succeeds_with_right_amount_and_currency() -> None:
    p = ManualLedgerProcessor()
    result = p.charge(12.34, "usd", "hosting", idempotency_key="k1")
    assert result.status is ChargeStatus.SUCCEEDED
    assert result.amount == 12.34
    assert result.currency == "usd"
    assert result.id.startswith("manual_")
    assert p.balance("usd") == 12.34


def test_charge_creates_distinct_ids() -> None:
    p = ManualLedgerProcessor()
    a = p.charge(1.00, "usd", "x", idempotency_key="k1")
    b = p.charge(1.00, "usd", "x", idempotency_key="k2")
    assert a.id != b.id


def test_full_refund_restores_balance_and_marks_refunded() -> None:
    p = ManualLedgerProcessor()
    charged = p.charge(50.00, "usd", "order", idempotency_key="k1")
    refunded = p.refund(charged.id)
    assert refunded.status is ChargeStatus.REFUNDED
    assert refunded.amount == 50.00
    assert p.balance("usd") == 0.0


def test_partial_refund_updates_balance_and_allows_second() -> None:
    p = ManualLedgerProcessor()
    charged = p.charge(50.00, "usd", "order", idempotency_key="k1")
    first = p.refund(charged.id, amount=20.00)
    assert first.status is ChargeStatus.SUCCEEDED
    assert p.balance("usd") == 30.00
    second = p.refund(charged.id, amount=30.00)
    assert second.status is ChargeStatus.REFUNDED
    assert p.balance("usd") == 0.0


def test_refund_over_charged_amount_raises() -> None:
    p = ManualLedgerProcessor()
    charged = p.charge(10.00, "usd", "order", idempotency_key="k1")
    with pytest.raises(ValueError, match="exceeds"):
        p.refund(charged.id, amount=10.01)
    assert p.balance("usd") == 10.00, "a refused refund must not move money"


def test_refund_after_full_refund_raises() -> None:
    p = ManualLedgerProcessor()
    charged = p.charge(10.00, "usd", "order", idempotency_key="k1")
    p.refund(charged.id)
    with pytest.raises(ValueError, match="exceeds"):
        p.refund(charged.id, amount=1.00)


def test_refund_unknown_charge_id_raises() -> None:
    p = ManualLedgerProcessor()
    with pytest.raises(ValueError, match="no charge with id"):
        p.refund("manual_doesnotexist", amount=1.00)


def test_refund_defaults_to_full_amount() -> None:
    p = ManualLedgerProcessor()
    charged = p.charge(7.50, "usd", "order", idempotency_key="k1")
    assert p.refund(charged.id).amount == 7.50
    assert p.balance("usd") == 0.0


def test_payout_debits_balance() -> None:
    p = ManualLedgerProcessor()
    p.charge(100.00, "usd", "income", idempotency_key="k1")
    result = p.payout(40.00, "usd", "acct_xyz", "withdraw")
    assert result.status is ChargeStatus.SUCCEEDED
    assert result.amount == 40.00
    assert p.balance("usd") == 60.00


def test_payout_insufficient_balance_raises() -> None:
    p = ManualLedgerProcessor()
    p.charge(5.00, "usd", "income", idempotency_key="k1")
    with pytest.raises(ValueError, match="exceeds"):
        p.payout(5.01, "usd", "acct_xyz", "withdraw")
    assert p.balance("usd") == 5.00, "a refused payout must not move money"


def test_payout_with_no_balance_raises() -> None:
    p = ManualLedgerProcessor()
    with pytest.raises(ValueError, match="exceeds"):
        p.payout(0.01, "usd", "acct_xyz", "withdraw")


def test_balance_net_of_charges_payouts_refunds() -> None:
    p = ManualLedgerProcessor()
    charged = p.charge(100.00, "usd", "income", idempotency_key="k1")
    p.refund(charged.id, amount=10.00)
    p.payout(30.00, "usd", "acct_xyz", "withdraw")
    assert p.balance("usd") == 60.00


def test_multiple_currencies_do_not_leak() -> None:
    p = ManualLedgerProcessor()
    usd_charge = p.charge(100.00, "usd", "income", idempotency_key="k1")
    eur_charge = p.charge(200.00, "eur", "income", idempotency_key="k2")

    assert p.balance("usd") == 100.00
    assert p.balance("eur") == 200.00

    p.refund(usd_charge.id, amount=25.00)
    p.payout(50.00, "eur", "acct_xyz", "withdraw")

    assert p.balance("usd") == 75.00
    assert p.balance("eur") == 150.00

    # A currency that was never touched stays at zero.
    assert p.balance("gbp") == 0.0

    # Refunding the eur charge moves only eur.
    p.refund(eur_charge.id, amount=100.00)
    assert p.balance("eur") == 50.00
    assert p.balance("usd") == 75.00


def test_minimum_charge_annotation_present() -> None:
    # The interface contract: processors declare the smallest chargeable amount
    # in their currency so the kernel can reject too-small spends up front.
    assert ManualLedgerProcessor.minimum_charge == 0.01
    assert isinstance(ManualLedgerProcessor().name, str)
    assert ManualLedgerProcessor.name == "manual"
