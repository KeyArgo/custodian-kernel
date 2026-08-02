"""Stripe payment-processor adapter for the Custodian kernel.

Implements ``custodian.processors.base.PaymentProcessor`` against the real
Stripe API using the official ``stripe`` SDK (``stripe>=9.0``) rather than
raw HTTP calls.

Amounts are exchanged in major units (e.g. ``10.50`` for ten dollars and fifty
cents) and converted to integer minor units (cents) for the Stripe API —
mirroring how ``balance()`` converts the SDK's cent-denominated responses
back into major units.
"""

from __future__ import annotations

import os
from typing import Any

import stripe

from custodian.processors.base import ChargeResult, ChargeStatus, PaymentProcessor


class StripeProcessor(PaymentProcessor):
    """PaymentProcessor backed by the Stripe API via the official SDK.

    Attributes:
        name: Processor identifier used by the kernel.
        minimum_charge: Stripe's real minimum USD charge (0.50).
    """

    name = "stripe"
    minimum_charge = 0.50

    def __init__(self, api_key: str | None = None):
        """Build a processor, resolving the API key from the argument or the
        ``STRIPE_API_KEY`` environment variable.

        Raises:
            RuntimeError: if no API key is available.
        """
        key = api_key or os.environ.get("STRIPE_API_KEY")
        if not key:
            raise RuntimeError(
                "No Stripe API key available: pass api_key=... or set the "
                "STRIPE_API_KEY environment variable."
            )
        self.api_key = key
        stripe.api_key = key

    @staticmethod
    def _to_minor_units(amount: float) -> int:
        """Convert a major-unit float amount to integer minor units (cents)."""
        return int(round(amount * 100))

    def charge(self, amount, currency, description, idempotency_key):
        """Create a PaymentIntent for ``amount`` in ``currency``.

        ``idempotency_key`` is passed through to Stripe's own request option,
        so a retried call cannot double-charge the customer.

        Stripe SDK errors (``stripe.error.StripeError``) are deliberately not
        caught: a failed charge must fail loudly, never report false success.
        """
        payment_intent = stripe.PaymentIntent.create(
            amount=self._to_minor_units(amount),
            currency=currency,
            description=description,
            idempotency_key=idempotency_key,
        )
        return ChargeResult(
            id=payment_intent.id,
            status=(
                ChargeStatus.SUCCEEDED
                if payment_intent.status == "succeeded"
                else ChargeStatus.PENDING
            ),
            amount=amount,
            currency=currency,
            raw=payment_intent.to_dict(),
        )

    def refund(self, charge_id, amount=None):
        """Refund a PaymentIntent, partial if ``amount`` (major units) is given,
        full otherwise.
        """
        params: dict[str, Any] = {"payment_intent": charge_id}
        if amount is not None:
            params["amount"] = self._to_minor_units(amount)
        refund = stripe.Refund.create(**params)
        return ChargeResult(
            id=refund.id,
            status=ChargeStatus.REFUNDED,
            amount=amount if amount is not None else refund.amount / 100,
            currency=refund.currency,
            raw=refund.to_dict(),
        )

    def payout(self, amount, currency, destination, description):
        """Create a Stripe Payout to ``destination``."""
        payout = stripe.Payout.create(
            amount=self._to_minor_units(amount),
            currency=currency,
            destination=destination,
            description=description,
        )
        return ChargeResult(
            id=payout.id,
            status=ChargeStatus.SUCCEEDED,
            amount=amount,
            currency=currency,
            raw=payout.to_dict(),
        )

    def balance(self, currency):
        """Return the available balance for ``currency`` in major units (float).

        Stripe returns available amounts as integer minor units (cents); these
        are converted to float major units, e.g. ``1050`` -> ``10.50``.
        """
        balance = stripe.Balance.retrieve()
        for item in balance.available:
            if item.currency == currency:
                return item.amount / 100.0
        return 0.0
