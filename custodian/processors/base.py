"""Vendor-neutral payment processor interface.

Concrete adapters (Stripe, Square, PayPal, a manual ledger, ...) implement
``PaymentProcessor``. The kernel's authority/spend gate only ever talks to
this interface — it must never import or reference a specific vendor SDK, so
the kernel can be tested (and shipped) with zero vendor dependency. A
Stripe-specific adapter can then be extracted into its own repo without
touching the kernel.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol


class ChargeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    PENDING = "pending"
    FAILED = "failed"
    REFUNDED = "refunded"


@dataclass(frozen=True)
class ChargeResult:
    id: str
    status: ChargeStatus
    amount: float
    currency: str
    # Processor-native response, kept for audit/debugging only. Policy code
    # must never branch on this field, only on the typed fields above, so the
    # kernel never has to understand any one vendor's response shape.
    raw: dict


class PaymentProcessor(Protocol):
    """Vendor-neutral payment processor interface. Concrete adapters
    (Stripe, Square, PayPal, a manual ledger, ...) implement this. The
    kernel's authority/spend gate only ever talks to this interface —
    it must never import or reference a specific vendor SDK."""

    name: str
    minimum_charge: float  # smallest chargeable amount in `currency` for this processor

    def charge(self, amount: float, currency: str, description: str, idempotency_key: str) -> ChargeResult: ...

    def refund(self, charge_id: str, amount: Optional[float] = None) -> ChargeResult: ...

    def payout(self, amount: float, currency: str, destination: str, description: str) -> ChargeResult: ...

    def balance(self, currency: str) -> float: ...


__all__ = [
    "ChargeStatus",
    "ChargeResult",
    "PaymentProcessor",
]
