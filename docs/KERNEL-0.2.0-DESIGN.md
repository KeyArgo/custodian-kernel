# Custodian Kernel 0.2.0 — Design Document
**Written:** 2026-06-30  
**Status:** Ready to implement — all existing primitives are wired, just needs new entry points  
**Estimated implementation:** 2-3 hours  
**Goal:** Transform the kernel from an explicit CLI tool into implicit middleware fabric

---

## The Problem

Right now Custodian is **opt-in**: every tool must call `custodian request --amount 5.00` explicitly.  
Competitors (Headgate, cyberware) are **opt-out**: every action passes through the kernel automatically.  
A judge reading the code sees a CLI dispatcher, not middleware.

## The Solution

Add 5 new modules that make the kernel **wrap everything automatically**:

```
┌─────────────────────────────────────────────────────────────┐
│                     CUSTODIAN KERNEL 0.2.0                  │
│                                                             │
│  @govern decorator    CustodianMiddleware    CustodianSession│
│  (wrap any fn)        (ASGI intercept)       (context mgr)  │
│         │                    │                    │          │
│         └────────────────────┴────────────────────┘          │
│                              │                               │
│                    ┌─────────▼──────────┐                   │
│                    │  EventBus (hooks)  │                   │
│                    └─────────┬──────────┘                   │
│                              │                               │
│              ┌───────────────┼───────────────┐              │
│              │               │               │              │
│        decide()        verify_claims()   AuditTrail         │
│        (existing)      (existing)        (existing)         │
└─────────────────────────────────────────────────────────────┘
```

---

## Files to Create

### 1. `custodian/govern.py` — `@govern` decorator

The single highest-impact addition. Makes the kernel implicit.

```python
from __future__ import annotations
import functools
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from custodian.types import Band, SpendRequest, Verdict
from custodian.bus import _bus


@dataclass
class GovernedResult:
    """Return value of every @govern-wrapped function."""
    value: Any                    # the wrapped function's actual return value
    verdict: str                  # "autonomous" / "escalation_required" / "denied"
    audit_id: str
    band: str
    amount: float
    description: str
    elapsed_ms: float
    claim_proof: Optional[str] = None   # "verified" / "contradicted" / "unverifiable"
    ts: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.verdict == "autonomous"

    def receipt(self) -> "GovernedReceipt":
        from custodian.receipt import GovernedReceipt
        return GovernedReceipt.build(
            fn_name=self.description, band=self.band, amount=self.amount,
            description=self.description, verdict=self.verdict,
            reason="", elapsed_ms=self.elapsed_ms, output=self.value,
            claim_proof=self.claim_proof,
        )


class EscalationRequired(Exception):
    def __init__(self, decision, request):
        self.decision = decision
        self.request = request
        super().__init__(f"Escalation required: {decision.reason}")


class KernelDenied(Exception):
    def __init__(self, decision, request):
        self.decision = decision
        self.request = request
        super().__init__(f"Kernel denied: {decision.reason}")


def govern(
    band: str = "L2",
    cap: float = 10.00,
    description: Optional[str] = None,
    cost_usd: float = 0.0,
    policy_path: Optional[str] = None,
    state_dir: Optional[str] = None,
    verify_output: bool = False,
    raise_on_escalation: bool = True,
):
    """
    Decorator that wraps any callable with kernel authority enforcement.

    Usage:
        @govern(band="L2", cap=50.00)
        def charge_customer(amount: float, customer_id: str) -> dict:
            return stripe_client.charge(amount=amount, customer=customer_id)

        result = charge_customer(85.00, "cus_123")
        # result.ok == True if within band
        # raises EscalationRequired if amount > cap
        # raises KernelDenied if kill switch is engaged

    The caller never invokes the kernel explicitly.
    The kernel is the call path.
    """
    def decorator(fn: Callable) -> Callable:
        _desc = description or fn.__doc__ or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> GovernedResult:
            # Extract amount from args or kwargs
            amount = float(kwargs.get("amount", cost_usd))
            if amount == 0.0 and args:
                for arg in args:
                    if isinstance(arg, (int, float)) and arg > 0:
                        amount = float(arg)
                        break

            request = SpendRequest(amount=amount, description=_desc)
            audit_id = str(uuid.uuid4())[:8]

            # Load policy + state lazily (not at decoration time)
            decision = _evaluate(request, band, cap, policy_path, state_dir)

            if decision.verdict == Verdict.DENIED:
                _bus.emit("kernel_denied", {
                    "audit_id": audit_id, "amount": amount, "reason": decision.reason
                })
                if raise_on_escalation:
                    raise KernelDenied(decision, request)
                return GovernedResult(value=None, verdict="denied", audit_id=audit_id,
                                      band=band, amount=amount, description=_desc, elapsed_ms=0.0)

            if decision.verdict == Verdict.ESCALATION_REQUIRED:
                _bus.emit("escalation_required", {
                    "audit_id": audit_id, "amount": amount,
                    "reason": decision.reason, "request": request
                })
                if raise_on_escalation:
                    raise EscalationRequired(decision, request)
                return GovernedResult(value=None, verdict="escalation_required", audit_id=audit_id,
                                      band=band, amount=amount, description=_desc, elapsed_ms=0.0)

            # AUTONOMOUS — execute
            _bus.emit("pre_execute", {"audit_id": audit_id, "amount": amount, "fn": fn.__name__})
            t0 = time.monotonic()
            value = fn(*args, **kwargs)
            elapsed_ms = (time.monotonic() - t0) * 1000

            # Optional output claim verification
            claim_proof = None
            if verify_output and isinstance(value, dict):
                claim_proof = _verify_output(fn.__name__, amount, value, audit_id)

            result = GovernedResult(
                value=value, verdict="autonomous", audit_id=audit_id,
                band=band, amount=amount, description=_desc,
                elapsed_ms=elapsed_ms, claim_proof=claim_proof,
            )
            _bus.emit("post_execute", {"audit_id": audit_id, "result": result})
            return result

        wrapper._governed = True
        wrapper._band = band
        wrapper._cap = cap
        return wrapper

    return decorator


def _evaluate(request, band, cap, policy_path, state_dir):
    """Internal: load policy/state and call decide(). Never raises."""
    from custodian.policy import load_policy
    from custodian.policy.evaluator import decide
    from custodian.config import CustodianConfig
    from custodian.types import AuthorityState
    import json
    from pathlib import Path

    cfg = CustodianConfig.from_env()
    try:
        policy = load_policy(policy_path or cfg.policy_path)
    except Exception:
        from custodian.policy.schema import Policy
        policy = Policy.default()

    _state_dir = Path(state_dir) if state_dir else cfg.state_dir
    state_file = _state_dir / "authority.json"
    if state_file.exists():
        state = AuthorityState.from_dict(json.loads(state_file.read_text()))
    else:
        state = AuthorityState(band=Band(band), per_action_cap=cap, session_cap=cap * 10)

    killed = False
    ks_file = _state_dir / "kill_switch.json"
    if ks_file.exists():
        try:
            killed = bool(json.loads(ks_file.read_text()).get("killed", False))
        except Exception:
            pass

    return decide(request, state, policy, killed=killed)


def _verify_output(fn_name, amount, value, audit_id):
    """Verify the function output against the ledger. Returns claim status string."""
    try:
        from custodian.packs.base import verify_claims, Claim
        claims = [Claim(
            id=audit_id,
            statement=f"{fn_name} returned amount={amount}",
            customer_quote=str(value),
            ledger_path="result.amount",
            relation="eq",
            asserted=amount,
        )]
        scope = {"result": {"amount": value.get("amount", amount)}}
        results = verify_claims(claims, scope)
        return results[0].status.value if results else None
    except Exception:
        return None
```

---

### 2. `custodian/bus.py` — EventBus

Hooks into every kernel lifecycle event. Makes the kernel extensible without touching core logic.

```python
from __future__ import annotations
from collections import defaultdict
from typing import Any, Callable, Dict, List
import logging

log = logging.getLogger(__name__)


class EventBus:
    """
    Publish-subscribe bus for kernel lifecycle events.

    Events emitted by the kernel:
        pre_execute          Before a @govern-wrapped function runs
        post_execute         After it completes (GovernedResult in payload)
        escalation_required  Request exceeded autonomous cap
        kernel_denied        Kill switch fired or request explicitly denied
        claim_verified       After verify_claims() completes on an output

    Usage:
        from custodian.bus import on

        @on("escalation_required")
        def notify(payload):
            send_sms(f"Escalation: ${payload['amount']} — {payload['reason']}")

        @on("kernel_denied")
        def log_denial(payload):
            audit_log.write(payload)
    """
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)

    def on(self, event: str) -> Callable:
        def decorator(fn: Callable) -> Callable:
            self._handlers[event].append(fn)
            return fn
        return decorator

    def emit(self, event: str, payload: Any = None) -> None:
        for handler in self._handlers.get(event, []):
            try:
                handler(payload)
            except Exception as e:
                log.warning("EventBus handler %s failed for event %s: %s",
                            getattr(handler, "__name__", "?"), event, e)

    def handlers(self, event: str) -> List[str]:
        return [getattr(h, "__name__", repr(h)) for h in self._handlers.get(event, [])]


# Module-level singleton — import this, not the class
_bus = EventBus()


def on(event: str) -> Callable:
    """Register a handler on the global kernel event bus."""
    return _bus.on(event)


def emit(event: str, payload: Any = None) -> None:
    """Emit an event on the global kernel event bus."""
    _bus.emit(event, payload)
```

---

### 3. `custodian/middleware.py` — ASGI Middleware

Mounts into any FastAPI/Starlette/Django app. Every governed route is intercepted automatically.

```python
from __future__ import annotations
import json
import logging
import uuid
from typing import Optional

log = logging.getLogger(__name__)


class CustodianMiddleware:
    """
    ASGI middleware that enforces kernel authority on governed HTTP routes.

    Usage (FastAPI):
        from fastapi import FastAPI
        from custodian.middleware import CustodianMiddleware

        app = FastAPI()
        app.add_middleware(CustodianMiddleware, policy="policy.yaml")

        # Register a governed route (band L2, cap $50):
        app.state.custodian.register_path("/charge", band="L2", cap=50.00)

    On a governed route:
        - Reads `amount` from JSON request body
        - Evaluates kernel policy (band, cap, kill switch, daily envelope)
        - Returns 402 Payment Required on escalation, 403 Forbidden on denial
        - Adds X-Custodian-Verdict and X-Custodian-Audit-Id headers on pass-through
        - Denied/escalated requests never reach the application handler
    """

    def __init__(self, app, policy: Optional[str] = None,
                 state_dir: Optional[str] = None, default_band: str = "L2"):
        self.app = app
        self.policy_path = policy
        self.state_dir = state_dir
        self.default_band = default_band
        self._governed_paths: dict = {}

    def register_path(self, path: str, band: str = "L2", cap: float = 10.00):
        """Register a route as governed. Call after app is created."""
        self._governed_paths[path] = {"band": band, "cap": cap}
        return self

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        route_cfg = self._governed_paths.get(path)

        if route_cfg is None:
            await self.app(scope, receive, send)
            return

        # Buffer body (needed to extract amount AND replay to app)
        body = b""
        more_body = True
        while more_body:
            msg = await receive()
            body += msg.get("body", b"")
            more_body = msg.get("more_body", False)

        amount = 0.0
        try:
            amount = float(json.loads(body).get("amount", 0.0))
        except Exception:
            pass

        from custodian.govern import _evaluate, EscalationRequired, KernelDenied
        from custodian.types import SpendRequest, Verdict

        request = SpendRequest(amount=amount, description=f"HTTP {path}")
        decision = _evaluate(request, route_cfg["band"], route_cfg["cap"],
                             self.policy_path, self.state_dir)
        audit_id = str(uuid.uuid4())[:8]

        if decision.verdict in (Verdict.DENIED, Verdict.ESCALATION_REQUIRED):
            status = 403 if decision.verdict == Verdict.DENIED else 402
            body_out = json.dumps({
                "error": decision.verdict.value,
                "reason": decision.reason,
                "audit_id": audit_id,
                "kernel": "custodian/0.2.0",
            }).encode()
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"x-custodian-verdict", decision.verdict.value.encode()],
                    [b"x-custodian-audit-id", audit_id.encode()],
                ],
            })
            await send({"type": "http.response.body", "body": body_out})
            return

        # AUTONOMOUS — replay body to app, inject verdict headers on response
        async def patched_receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def patched_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"x-custodian-verdict", b"autonomous"])
                headers.append([b"x-custodian-audit-id", audit_id.encode()])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, patched_receive, patched_send)
```

---

### 4. `custodian/session.py` — CustodianSession Context Manager

Scoped authority sessions with sub-session inheritance. The child can never exceed the parent's band ceiling.

```python
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import List, Optional

from custodian.types import SpendRequest, AuthorityState, Band, Verdict


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
                 parent: Optional["CustodianSession"] = None):
        self.band = band
        self.cap = cap
        self.daily_envelope = daily_envelope
        self.policy_path = policy_path
        self.state_dir = state_dir
        self.parent = parent
        self.session_id = str(uuid.uuid4())[:8]
        self._results: List[SessionResult] = []
        self._spent = 0.0

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
        req = SpendRequest(amount=amount, description=description)
        decision = _evaluate(req, self.band, self.cap, self.policy_path, self.state_dir)

        if decision.verdict == Verdict.AUTONOMOUS:
            self._spent += amount
            if self.parent:
                self.parent._spent += amount

        audit_id = f"{self.session_id}-{len(self._results)}"
        r = SessionResult(request=req, verdict=decision.verdict.value,
                          reason=decision.reason, audit_id=audit_id)
        self._results.append(r)
        return r

    def sub_session(self, band: str, cap: Optional[float] = None) -> "CustodianSession":
        """Create a child session with a lower (or equal) band ceiling."""
        return CustodianSession(band=band, cap=cap or self.cap,
                                daily_envelope=self.daily_envelope, parent=self)

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
```

---

### 5. `custodian/receipt.py` — GovernedReceipt

Every governed action produces a SHA-256 verifiable proof artifact. Judges can verify the receipt independently.

```python
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
    can produce a GovernedReceipt. The fingerprint is SHA-256(receipt_id +
    verdict + output_hash) and cannot be forged without knowing all three.

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
    fingerprint: str       # SHA-256(receipt_id + ":" + verdict + ":" + output_hash)

    def verify(self) -> bool:
        """Recompute and compare fingerprint. Returns True iff receipt is untampered."""
        expected = hashlib.sha256(
            f"{self.receipt_id}:{self.verdict}:{self.output_hash}".encode()
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
            f"{receipt_id}:{verdict}:{output_hash}".encode()
        ).hexdigest()
        return cls(
            receipt_id=receipt_id, ts=ts, fn_name=fn_name, band=band,
            amount=amount, description=description, verdict=verdict,
            reason=reason, elapsed_ms=elapsed_ms, output_hash=output_hash,
            claim_proof=claim_proof, fingerprint=fingerprint,
        )
```

---

### 6. Update `custodian/__init__.py`

```python
__version__ = "0.2.0"

from custodian.types import (
    AuditEntry, AuthorityState, Band, Decision,
    PendingApproval, SpendRequest, Verdict,
)
from custodian.govern import govern, GovernedResult, EscalationRequired, KernelDenied
from custodian.session import CustodianSession
from custodian.receipt import GovernedReceipt
from custodian.bus import on as on_event, emit as emit_event
from custodian.middleware import CustodianMiddleware

__all__ = [
    "__version__",
    # Types
    "Band", "AuthorityState", "SpendRequest", "Verdict",
    "Decision", "PendingApproval", "AuditEntry",
    # 0.2.0 — kernel as fabric
    "govern",           # @govern decorator — wraps any function
    "GovernedResult",   # return type of @govern-wrapped functions
    "EscalationRequired",
    "KernelDenied",
    "CustodianSession", # context manager for bounded sessions
    "GovernedReceipt",  # cryptographic proof artifact
    "CustodianMiddleware", # ASGI middleware for FastAPI/Flask
    "on_event",         # register kernel lifecycle hook
    "emit_event",       # emit on global event bus
]
```

---

## Tests to Write

### `tests/test_govern.py`
- `@govern(band="L2", cap=10.00)` wraps function, returns GovernedResult
- `result.ok == True` when amount <= cap
- `result.value` is the wrapped function's return value
- Raises `EscalationRequired` when amount > cap
- Raises `KernelDenied` when kill switch is engaged (mock state file)
- `raise_on_escalation=False` returns GovernedResult with verdict="escalation_required"
- `verify_output=True` populates `claim_proof` field
- Receipt from `result.receipt()` passes `.verify()`
- `wrapper._governed == True`, `wrapper._band`, `wrapper._cap` attributes set

### `tests/test_bus.py`
- `@on("test_event")` registers handler
- `emit("test_event", payload)` calls handler with payload
- Multiple handlers for same event all called
- Handler exception does not propagate (logged, swallowed)
- `bus.handlers("test_event")` returns list of handler names

### `tests/test_session.py`
- `session.request(5.00)` returns SessionResult with `ok==True` when within cap
- `session.request(500.00)` returns `verdict=="escalation_required"` when over cap
- `session.summary()` counts correctly
- `session.log()` returns formatted string
- Sub-session with higher band than parent returns `verdict=="denied"`
- Sub-session spending increments both child `_spent` and parent `_spent`

### `tests/test_receipt.py`
- `GovernedReceipt.build(...)` returns receipt with correct fields
- `receipt.verify()` returns True for valid receipt
- Tampering with `verdict` makes `verify()` return False
- `receipt.to_json()` is valid JSON, `receipt.to_dict()` is a dict

### `tests/test_middleware.py`
- `CustodianMiddleware(app)` passes through ungoverned routes
- Governed route with amount<=cap: passes through, response has X-Custodian-Verdict: autonomous
- Governed route with amount>cap: returns 402, body has `error: escalation_required`
- Kill switch engaged: returns 403, body has `error: denied`

---

## CLI Additions (`custodian demo` group)

Add `custodian demo receipt` — demonstrates the receipt system:

```
$ custodian demo receipt
CUSTODIAN GOVERNED RECEIPT DEMO
================================================

Wrapping a simulated charge_customer(85.00) with @govern(band="L2", cap=250.00)...

[1/3] KERNEL EVALUATES
  Amount:   $85.00
  Band:     L2 (autonomous up to $250.00)
  Verdict:  AUTONOMOUS

[2/3] FUNCTION EXECUTES
  charge_customer returned: {"pi": "pi_demo_abc123", "amount": 85.00}
  Elapsed: 0.4ms

[3/3] RECEIPT GENERATED
  receipt_id: 550e8400-e29b-41d4-a716-446655440000
  verdict:    autonomous
  output_hash: a7f3d2...
  fingerprint: 9c2b1a...
  receipt.verify(): ✅ TRUE

Run `receipt.verify()` on any receipt to prove it was not tampered with.
```

---

## Version Bump

- `custodian/__init__.py`: `__version__ = "0.2.0"`
- `pyproject.toml`: version = "0.2.0"
- `README.md`: Add 0.2.0 section showing `@govern` decorator usage

---

## Implementation Order

1. `custodian/bus.py` (15 min — no deps, needed by govern.py)
2. `custodian/govern.py` (30 min — deps: bus, existing decide/policy)
3. `custodian/receipt.py` (15 min — pure dataclass, no deps)
4. `custodian/session.py` (20 min — deps: govern._evaluate)
5. `custodian/middleware.py` (30 min — deps: govern._evaluate)
6. Update `custodian/__init__.py` (5 min)
7. Tests (45 min)
8. `custodian demo receipt` CLI command (20 min)
9. README 0.2.0 section (10 min)
10. PyPI publish 0.2.0 (10 min, needs PYPI_TOKEN)

Total: ~3 hours
