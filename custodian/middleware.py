from __future__ import annotations
import json
import logging
import math
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
        middleware = CustodianMiddleware(app, policy="policy.yaml")
        middleware.register_path("/charge", band="L2", cap=50.00)

    On a governed route:
        - Reads `amount` from JSON request body
        - Evaluates kernel policy (band, cap, kill switch, daily envelope)
        - Returns 402 Payment Required on escalation, 403 Forbidden on denial
        - Adds X-Custodian-Verdict and X-Custodian-Audit-Id headers on pass-through
        - Denied/escalated requests never reach the application handler
    """

    def __init__(self, app, policy: Optional[str] = None,
                 state_dir: Optional[str] = None, default_band: str = "L2",
                 value_free_cap: float = 10.00,
                 max_body_bytes: int = 1_048_576):
        self.app = app
        self.policy_path = policy
        self.state_dir = state_dir
        self.default_band = default_band
        self.value_free_cap = value_free_cap
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.max_body_bytes = int(max_body_bytes)
        self._governed_paths: dict = {}
        self._value_free_paths: list = []  # auto-route: /__custodian__/plan etc.

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a request path before matching it against registered
        governed routes.

        A byte-for-byte-only match against scope["path"] let a request
        differing only by a trailing slash, a doubled leading slash, or
        case reach the downstream application completely ungoverned --
        no band/cap/kill-switch check, no audit trail at all. Reproduced:
        a route registered as /charge (L4, always-escalates) let a
        $999,999 request through as an ordinary 200 via /charge/,
        //charge, or /CHARGE. Found in review.
        """
        segments = [s for s in (path or "").strip().split("/") if s]
        return ("/" + "/".join(segments)).lower()

    def register_path(self, path: str, band: str = "L2", cap: float = 10.00):
        """Register a route as governed. Returns self for chaining."""
        self._governed_paths[self._normalize_path(path)] = {"band": band, "cap": cap}
        return self

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = self._normalize_path(scope.get("path", ""))

        # Value-free plan endpoint: /__custodian__/plan
        if path == "/__custodian__/plan":
            body = await self._read_body(receive)
            if body is None:
                await self._send_json(send, 413, {"error": "request-body-too-large"})
                return
            result = await self._handle_value_free_plan(body)
            status = result.pop("status", 200)
            await self._send_json(send, status, result)
            return

        route_cfg = self._governed_paths.get(path)

        if route_cfg is None:
            await self.app(scope, receive, send)
            return

        # Buffer body — needed to extract amount AND replay to the app
        body = await self._read_body(receive)
        if body is None:
            await self._send_json(send, 413, {"error": "request-body-too-large"})
            return

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            await self._send_json(send, 400, {"error": "invalid-json"})
            return
        if not isinstance(data, dict):
            await self._send_json(send, 400, {"error": "json-object-required"})
            return
        if "amount" not in data:
            await self._send_json(send, 400, {"error": "missing-amount"})
            return
        if isinstance(data["amount"], bool):
            await self._send_json(send, 400, {"error": "invalid-amount"})
            return
        try:
            amount = float(data["amount"])
        except (TypeError, ValueError, OverflowError):
            await self._send_json(send, 400, {"error": "invalid-amount"})
            return
        if not math.isfinite(amount):
            await self._send_json(send, 400, {"error": "non-finite-amount"})
            return

        from custodian.govern import _evaluate
        from custodian.types import SpendRequest, Verdict

        request = SpendRequest(amount=amount, description=f"HTTP {path}")
        decision = _evaluate(request, route_cfg["band"], route_cfg["cap"],
                             self.policy_path, self.state_dir)
        audit_id = str(uuid.uuid4())[:8]

        if decision.verdict in (Verdict.DENIED, Verdict.ESCALATION_REQUIRED):
            status = 403 if decision.verdict == Verdict.DENIED else 402
            response = {
                "error": decision.verdict.value,
                "reason": decision.reason,
                "audit_id": audit_id,
                "kernel": "custodian/0.4.0",
            }
            await self._send_json(send, status, response, headers=[
                [b"x-custodian-verdict", decision.verdict.value.encode()],
                [b"x-custodian-audit-id", audit_id.encode()],
            ])
            return

        # AUTONOMOUS — replay buffered body to app, inject verdict headers on response
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

    async def _read_body(self, receive) -> Optional[bytes]:
        body = bytearray()
        more_body = True
        while more_body:
            msg = await receive()
            if msg.get("type") == "http.disconnect":
                return None
            body.extend(msg.get("body", b""))
            if len(body) > self.max_body_bytes:
                return None
            more_body = msg.get("more_body", False)
        return bytes(body)

    @staticmethod
    async def _send_json(send, status: int, payload: dict,
                         headers: Optional[list] = None) -> None:
        response_headers = [[b"content-type", b"application/json"]]
        response_headers.extend(headers or [])
        await send({"type": "http.response.start", "status": status,
                    "headers": response_headers})
        await send({"type": "http.response.body",
                    "body": json.dumps(payload, allow_nan=False).encode("utf-8")})

    # ── value-free plan endpoint ──────────────────────────────────────────────

    async def _handle_value_free_plan(self, body: bytes) -> dict:
        """Handle a value-free plan request: authorize schema only."""
        from custodian.govern import _evaluate
        from custodian.types import (
            SpendRequest, Verdict, sanitize_dict,
        )

        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"error": "invalid-json", "status": 400}
        if not isinstance(data, dict):
            return {"error": "json-object-required", "status": 400}

        # Required fields: skill, perk, var_keys
        skill = data.get("skill")
        perk = data.get("perk")
        var_keys_raw = data.get("var_keys")

        if not skill or not perk or not var_keys_raw:
            return {
                "error": "missing-fields",
                "status": 400,
                # Operator precedence in the old list comprehension made
                # `not (f == "skill" and skill)` true for every f != "skill",
                # so "perk" and "var_keys" were reported as missing even when
                # both were present. Found in review.
                "missing": [f for f, v in
                            (("skill", skill), ("perk", perk), ("var_keys", var_keys_raw))
                            if not v],
            }

        if (not isinstance(var_keys_raw, list)
                or not all(isinstance(item, str) and item for item in var_keys_raw)):
            return {"error": "var-keys-must-be-nonempty-string-list", "status": 400}
        var_keys = set(var_keys_raw)
        band = data.get("band", self.default_band)

        # Sanitize the request before audit (never log secrets)
        sanitize_dict(data)

        # Evaluate kernel policy
        request = SpendRequest(
            amount=0.0,
            description=f"value-free-plan:{skill}/{perk}",
        )
        decision = _evaluate(request, band, self.value_free_cap,
                             self.policy_path, self.state_dir)
        audit_id = str(uuid.uuid4())[:8]

        if decision.verdict != Verdict.AUTONOMOUS:
            return {
                "verdict": decision.verdict.value,
                "reason": decision.reason,
                "audit_id": audit_id,
                "status": 403,
            }

        # Build the plan
        import hashlib
        fp = hashlib.sha256(
            json.dumps({"s": skill, "p": perk, "k": sorted(var_keys)}, sort_keys=True).encode()
        ).hexdigest()

        return {
            "fingerprint": fp,
            "skill": skill,
            "perk": perk,
            "var_keys": sorted(var_keys),
            "band": band,
            "cap": self.value_free_cap,
            "verdict": "authorized",
            "audit_id": audit_id,
            "status": 200,
        }
