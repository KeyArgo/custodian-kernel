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
    SHA-256(receipt_id:fn_name:band:amount:verdict:reason:description:claim_proof:output_hash),
    covering every semantically load-bearing field — changing any one
    invalidates verify(). In particular claim_proof (the verifier's
    VERIFIED/CONTRADICTED/UNVERIFIABLE result) is inside the hash, so a receipt
    cannot be edited to claim it passed verification when it did not. Only the
    non-semantic timing fields (ts, elapsed_ms) are outside the hash.

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
    fingerprint: str       # see _compute_fingerprint for covered fields

    @staticmethod
    def _compute_fingerprint(receipt_id: str, fn_name: str, band: str, amount: float,
                             verdict: str, reason: str, description: str,
                             claim_proof: Optional[str], output_hash: str) -> str:
        return hashlib.sha256(
            f"{receipt_id}:{fn_name}:{band}:{amount}:{verdict}:{reason}:"
            f"{description}:{claim_proof}:{output_hash}".encode()
        ).hexdigest()

    def verify(self) -> bool:
        """Recompute and compare fingerprint. Returns True iff receipt is untampered."""
        expected = self._compute_fingerprint(
            self.receipt_id, self.fn_name, self.band, self.amount, self.verdict,
            self.reason, self.description, self.claim_proof, self.output_hash,
        )
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
        fingerprint = cls._compute_fingerprint(
            receipt_id, fn_name, band, amount, verdict, reason, description,
            claim_proof, output_hash,
        )
        return cls(
            receipt_id=receipt_id, ts=ts, fn_name=fn_name, band=band,
            amount=amount, description=description, verdict=verdict,
            reason=reason, elapsed_ms=elapsed_ms, output_hash=output_hash,
            claim_proof=claim_proof, fingerprint=fingerprint,
        )
