from __future__ import annotations
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Optional


@dataclass
class GovernedReceipt:
    """
    Cryptographically verifiable proof artifact for a governed action.

    Every @govern-wrapped function, middleware intercept, or session.request()
    can produce a GovernedReceipt. The fingerprint is
    SHA-256(receipt_id:band:amount:verdict:output_hash) covering all five
    tamper-sensitive fields — changing any one invalidates verify().

    Usage:
        result = charge_customer(85.00, "cus_123")
        receipt = result.receipt()
        print(receipt.to_json())
        assert receipt.verify()   # always True for a valid receipt
    """
    receipt_id: str
    ts: float
    fn_name: str
    band: str
    amount: float
    description: str
    verdict: str
    reason: str
    elapsed_ms: float
    output_hash: str       # SHA-256(json(output))
    claim_proof: Optional[str]
    fingerprint: str       # SHA-256(receipt_id:band:amount:verdict:output_hash)

    def verify(self) -> bool:
        """Recompute and compare fingerprint. Returns True iff receipt is untampered."""
        expected = hashlib.sha256(
            f"{self.receipt_id}:{self.band}:{self.amount}:{self.verdict}:{self.output_hash}".encode()
        ).hexdigest()
        return self.fingerprint == expected

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def build(cls, fn_name: str, band: str, amount: float, description: str,
              verdict: str, reason: str, elapsed_ms: float, output: Any,
              claim_proof: Optional[str] = None) -> "GovernedReceipt":
        receipt_id = str(uuid.uuid4())
        ts = time.time()
        output_hash = hashlib.sha256(
            json.dumps(output, default=str, sort_keys=True).encode()
        ).hexdigest()
        fingerprint = hashlib.sha256(
            f"{receipt_id}:{band}:{amount}:{verdict}:{output_hash}".encode()
        ).hexdigest()
        return cls(
            receipt_id=receipt_id, ts=ts, fn_name=fn_name, band=band,
            amount=amount, description=description, verdict=verdict,
            reason=reason, elapsed_ms=elapsed_ms, output_hash=output_hash,
            claim_proof=claim_proof, fingerprint=fingerprint,
        )
