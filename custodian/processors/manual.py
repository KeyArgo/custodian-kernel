"""ManualLedgerProcessor — a pure in-memory reference implementation.

Implements :class:`custodian.processors.base.PaymentProcessor` with no network
calls and no vendor SDK, so the kernel's authority/spend gate can be tested
end-to-end (and the interface itself proven vendor-neutral) without installing
any real payment processor.

All state lives in process memory, keyed by currency, and is kept consistent
across ``charge()`` / ``refund()`` / ``payout()`` / ``balance()`` calls.
"""
from __future__ import annotations

import uuid
from typing import Optional

from custodian.processors.base import ChargeResult, ChargeStatus


class ManualLedgerProcessor:
    """In-memory ledger implementing the PaymentProcessor protocol.

    ``name`` and ``minimum_charge`` are class attributes so the protocol's
    ``name``/``minimum_charge`` annotations are satisfied without instance
    state. Each instance keeps its own ledger and charge records.
    """

    name = "manual"
    minimum_charge = 0.01

    def __init__(self) -> None:
        self._balances: dict[str, float] = {}
        # charge_id -> {"amount": float, "currency": str, "refunded": float}
        self._charges: dict[str, dict] = {}

    def _balance_of(self, currency: str) -> float:
        return round(self._balances.get(currency, 0.0), 2)

    def charge(self, amount: float, currency: str, description: str, idempotency_key: str) -> ChargeResult:
        charge_id = f"manual_{uuid.uuid4().hex}"
        self._charges[charge_id] = {"amount": amount, "currency": currency, "refunded": 0.0}
        self._balances[currency] = round(self._balance_of(currency) + amount, 2)
        return ChargeResult(
            id=charge_id,
            status=ChargeStatus.SUCCEEDED,
            amount=amount,
            currency=currency,
            raw={"processor": "manual", "description": description, "idempotency_key": idempotency_key},
        )

    def refund(self, charge_id: str, amount: Optional[float] = None) -> ChargeResult:
        try:
            record = self._charges[charge_id]
        except KeyError:
            raise ValueError(f"no charge with id {charge_id!r} in this manual ledger") from None
        if amount is None:
            amount = record["amount"]
        remaining = round(record["amount"] - record["refunded"], 2)
        if amount > remaining:
            raise ValueError(
                f"refund of {amount:.2f} {record['currency']} exceeds the "
                f"{remaining:.2f} remaining on charge {charge_id!r}"
            )
        if amount > 0:
            record["refunded"] = round(record["refunded"] + amount, 2)
            currency = record["currency"]
            self._balances[currency] = round(self._balance_of(currency) - amount, 2)
        status = (
            ChargeStatus.REFUNDED
            if record["refunded"] == record["amount"]
            else ChargeStatus.SUCCEEDED
        )
        return ChargeResult(
            id=f"refund_{charge_id}",
            status=status,
            amount=amount,
            currency=record["currency"],
            raw={"processor": "manual", "charge_id": charge_id},
        )

    def payout(self, amount: float, currency: str, destination: str, description: str) -> ChargeResult:
        if amount > self._balance_of(currency):
            raise ValueError(
                f"payout of {amount:.2f} {currency} exceeds the "
                f"{self._balance_of(currency):.2f} {currency} available"
            )
        self._balances[currency] = round(self._balance_of(currency) - amount, 2)
        return ChargeResult(
            id=f"manual_payout_{uuid.uuid4().hex}",
            status=ChargeStatus.SUCCEEDED,
            amount=amount,
            currency=currency,
            raw={"processor": "manual", "destination": destination, "description": description},
        )

    def balance(self, currency: str) -> float:
        return self._balance_of(currency)


__all__ = ["ManualLedgerProcessor"]
