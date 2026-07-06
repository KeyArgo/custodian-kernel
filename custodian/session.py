from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import List, Optional

from custodian.types import SpendRequest, Verdict


@dataclass
class SessionResult:
    request: SpendRequest
    verdict: str
    reason: str
    audit_id: str

    @property
    def ok(self) -> bool:
        return self.verdict == "autonomous"


class CustodianSession:
    """
    Context manager for a bounded, governed execution session.

    Usage:
        with CustodianSession(band="L2", cap=10.00) as session:
            r = session.request(amount=5.00, description="API call")
            if r.ok:
                do_thing()
            print(session.log())

    Sub-sessions (child cannot exceed parent band):
        with CustodianSession(band="L2", cap=100.00) as outer:
            with outer.sub_session(band="L1") as inner:
                r = inner.request(amount=1.00)
                # r.verdict == "denied" — L1 cannot spend
    """

    _BAND_RANK = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}

    def __init__(self, band: str = "L2", cap: float = 10.00,
                 daily_envelope: float = 50.00,
                 policy_path: Optional[str] = None,
                 state_dir: Optional[str] = None,
                 parent: Optional["CustodianSession"] = None,
                 step: Optional[str] = None):
        self.band = band
        self.cap = cap
        self.daily_envelope = daily_envelope
        self.policy_path = policy_path
        self.state_dir = state_dir
        self.parent = parent
        self.session_id = str(uuid.uuid4())[:8]
        self._results: List[SessionResult] = []
        self._spent = 0.0
        self._step = step          # human-readable step label (e.g. "step-02")
        self._parents_audit: List[str] = []  # audit_ids inherited from parent

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def request(self, amount: float, description: str = "",
                skill: Optional[str] = None,
                context: Optional[dict] = None) -> SessionResult:
        # Child cannot exceed parent band ceiling
        if self.parent is not None:
            my_rank = self._BAND_RANK.get(self.band, 0)
            parent_rank = self._BAND_RANK.get(self.parent.band, 0)
            if my_rank > parent_rank:
                r = SessionResult(
                    request=SpendRequest(amount=amount, description=description),
                    verdict="denied",
                    reason=f"sub-session band {self.band} exceeds parent ceiling {self.parent.band}",
                    audit_id=f"{self.session_id}-{len(self._results)}",
                )
                self._results.append(r)
                return r

        from custodian.govern import _evaluate
        from custodian.types import Verdict

        req = SpendRequest(amount=amount, description=description)
        decision = _evaluate(req, self.band, self.cap, self.policy_path, self.state_dir)

        # Upstream step ordering check: if this session has a step label,
        # every parent audit_id must have succeeded (autonomous) in the
        # parent session.  Pattern from cyberware's upstream_step_gate.
        if self._step is not None and self.parent is not None:
            for parent_audit in self._parents_audit:
                parent_ok = any(
                    r.audit_id == parent_audit and r.verdict == "autonomous"
                    for r in self.parent._results
                )
                if not parent_ok:
                    r = SessionResult(
                        request=req,
                        verdict="denied",
                        reason=(
                            f"upstream step {parent_audit} "
                            f"(step before {self._step}) "
                            f"did not produce an autonomous result"
                        ),
                        audit_id=f"{self.session_id}-{len(self._results)}",
                    )
                    self._results.append(r)
                    return r

        if decision.verdict == Verdict.AUTONOMOUS:
            self._spent += amount
            ancestor = self.parent
            while ancestor is not None:
                ancestor._spent += amount
                ancestor = ancestor.parent

        audit_id = f"{self.session_id}-{len(self._results)}"
        r = SessionResult(request=req, verdict=decision.verdict.value,
                          reason=decision.reason, audit_id=audit_id)
        self._results.append(r)
        return r

    def sub_session(self, band: str, cap: Optional[float] = None) -> "CustodianSession":
        """Create a child session with a lower (or equal) band ceiling."""
        return CustodianSession(band=band, cap=cap if cap is not None else self.cap,
                                daily_envelope=self.daily_envelope,
                                policy_path=self.policy_path, state_dir=self.state_dir,
                                parent=self)

    def log(self) -> str:
        lines = [f"CustodianSession {self.session_id} — "
                 f"{len(self._results)} decisions, ${self._spent:.4f} spent"]
        for r in self._results:
            lines.append(
                f"  [{r.audit_id}] {r.verdict.upper():<22} "
                f"${r.request.amount:>8.2f}  {r.request.description[:50]}"
            )
        return "\n".join(lines)

    def summary(self) -> dict:
        from collections import Counter
        v = Counter(r.verdict for r in self._results)
        return {
            "session_id": self.session_id,
            "total": len(self._results),
            "spent_usd": round(self._spent, 6),
            "autonomous": v.get("autonomous", 0),
            "escalated": v.get("escalation_required", 0),
            "denied": v.get("denied", 0),
        }
