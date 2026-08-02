"""Unit tests for StripeProcessor with the stripe SDK fully mocked.

No real network calls, no real API keys: every stripe module the processor
touches is monkeypatched before each test.
"""

import pytest
import stripe

from custodian_stripe.processor import StripeProcessor
from custodian.processors.base import ChargeStatus


class _FakeStripeResponse:
    """Minimal stand-in for stripe's StripeObject: attribute access + to_dict()."""

    def __init__(self, **kwargs):
        self._data = dict(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        return dict(self._data)


def _make_processor(monkeypatch, api_key="sk_test_123"):
    return StripeProcessor(api_key=api_key)


def test_constructor_raises_without_key_or_env(monkeypatch):
    monkeypatch.delenv("STRIPE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="STRIPE_API_KEY"):
        StripeProcessor()


def test_constructor_reads_key_from_env(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_env")
    processor = StripeProcessor()
    assert processor.api_key == "sk_test_env"
    assert stripe.api_key == "sk_test_env"


def test_constructor_explicit_key_wins_over_env(monkeypatch):
    monkeypatch.setenv("STRIPE_API_KEY", "sk_test_env")
    processor = StripeProcessor(api_key="sk_test_explicit")
    assert processor.api_key == "sk_test_explicit"
    assert stripe.api_key == "sk_test_explicit"


def test_charge_returns_charge_result_and_passes_idempotency_key(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeStripeResponse(
            id="pi_1ABC", status="succeeded", amount=kwargs["amount"],
            currency=kwargs["currency"],
        )

    monkeypatch.setattr(stripe, "PaymentIntent", type("PI", (), {"create": staticmethod(fake_create)}))

    result = _make_processor(monkeypatch).charge(
        amount=10.50,
        currency="usd",
        description="test charge",
        idempotency_key="idem-abc-123",
    )

    assert captured["amount"] == 1050
    assert captured["currency"] == "usd"
    assert captured["description"] == "test charge"
    assert captured["idempotency_key"] == "idem-abc-123"

    assert result.id == "pi_1ABC"
    assert result.status is ChargeStatus.SUCCEEDED
    assert result.amount == 10.50
    assert result.currency == "usd"
    assert isinstance(result.raw, dict)
    assert result.raw["id"] == "pi_1ABC"


def test_charge_reports_pending_for_unsucceeded_status(monkeypatch):
    def fake_create(**kwargs):
        return _FakeStripeResponse(
            id="pi_1ABC", status="requires_action", amount=kwargs["amount"],
            currency=kwargs["currency"],
        )

    monkeypatch.setattr(stripe, "PaymentIntent", type("PI", (), {"create": staticmethod(fake_create)}))

    result = _make_processor(monkeypatch).charge(
        amount=10.50, currency="usd", description="d", idempotency_key="k"
    )

    assert result.status is ChargeStatus.PENDING


def test_charge_propagates_stripe_error(monkeypatch):
    def fake_create(**kwargs):
        raise stripe.error.StripeError("card declined")

    monkeypatch.setattr(stripe, "PaymentIntent", type("PI", (), {"create": staticmethod(fake_create)}))

    with pytest.raises(stripe.error.StripeError):
        _make_processor(monkeypatch).charge(
            amount=10.50, currency="usd", description="d", idempotency_key="k"
        )


def test_refund_full(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeStripeResponse(id="re_1ABC", amount=1050, currency="usd")

    monkeypatch.setattr(stripe, "Refund", type("R", (), {"create": staticmethod(fake_create)}))

    result = _make_processor(monkeypatch).refund("pi_1ABC")

    assert captured == {"payment_intent": "pi_1ABC"}
    assert result.id == "re_1ABC"
    assert result.status is ChargeStatus.REFUNDED
    assert result.amount == 10.50
    assert result.currency == "usd"
    assert isinstance(result.raw, dict)


def test_refund_partial(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeStripeResponse(id="re_1ABC", amount=500, currency="usd")

    monkeypatch.setattr(stripe, "Refund", type("R", (), {"create": staticmethod(fake_create)}))

    result = _make_processor(monkeypatch).refund("pi_1ABC", amount=5.00)

    assert captured == {"payment_intent": "pi_1ABC", "amount": 500}
    assert result.status is ChargeStatus.REFUNDED
    assert result.amount == 5.00


def test_payout_succeeded(monkeypatch):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeStripeResponse(
            id="po_1ABC", amount=kwargs["amount"], currency=kwargs["currency"]
        )

    monkeypatch.setattr(stripe, "Payout", type("PO", (), {"create": staticmethod(fake_create)}))

    result = _make_processor(monkeypatch).payout(
        amount=100.00, currency="usd", destination="ba_123", description="sweep"
    )

    assert captured["amount"] == 10000
    assert captured["currency"] == "usd"
    assert captured["destination"] == "ba_123"
    assert captured["description"] == "sweep"
    assert result.id == "po_1ABC"
    assert result.status is ChargeStatus.SUCCEEDED
    assert result.amount == 100.00
    assert result.currency == "usd"


def test_balance_converts_cents_to_major_units(monkeypatch):
    def fake_retrieve():
        return _FakeStripeResponse(
            available=[
                _FakeStripeResponse(currency="usd", amount=1050),
                _FakeStripeResponse(currency="eur", amount=499),
            ]
        )

    monkeypatch.setattr(stripe, "Balance", type("B", (), {"retrieve": staticmethod(fake_retrieve)}))

    processor = _make_processor(monkeypatch)
    assert processor.balance("usd") == 10.50
    assert processor.balance("eur") == 4.99
