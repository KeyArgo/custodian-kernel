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
                 value_free_cap: float = 10.00):
        self.app = app
        self.policy_path = policy
        self.state_dir = state_dir
        self.default_band = default_band
        self.value_free_cap = value_free_cap
        self._governed_paths: dict = {}
        self._value_free_paths: list = []  # auto-route: /__custodian__/plan etc.

    def register_path(self, path: str, band: str = "L2", cap: float = 10.00):
        """Register a route as governed. Returns self for chaining."""
        self._governed_paths[path] = {"band": band, "cap": cap}
        return self

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Value-free plan endpoint: /__custodian__/plan
        if path == "/__custodian__/plan":
            body = b""
            more_body = True
            while more_body:
                msg = await receive()
                body += msg.get("body", b"")
                more_body = msg.get("more_body", False)
            result = await self._handle_value_free_plan(body)
            status = result.pop("status", 200)
            body_out = json.dumps(result).encode()
            await send({
                "type": "http.response.start",
                "status": status,
                "headers": [
                    [b"content-type", b"application/json"],
                ],
            })
            await send({"type": "http.response.body", "body": body_out})
            return

        route_cfg = self._governed_paths.get(path)

        if route_cfg is None:
            await self.app(scope, receive, send)
            return

        # Buffer body — needed to extract amount AND replay to the app
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

        from custodian.govern import _evaluate
        from custodian.types import SpendRequest, Verdict, sanitize_dict

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

    # ── value-free plan endpoint ──────────────────────────────────────────────

    async def _handle_value_free_plan(self, body: bytes) -> dict:
        """Handle a value-free plan request: authorize schema only."""
        from custodian.govern import _evaluate
        from custodian.types import (
            SpendRequest, Verdict, sanitize_dict,
        )

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return {"error": "invalid-json", "status": 400}

        # Required fields: skill, perk, var_keys
        skill = data.get("skill")
        perk = data.get("perk")
        var_keys_raw = data.get("var_keys")

        if not skill or not perk or not var_keys_raw:
            return {
                "error": "missing-fields",
                "status": 400,
                "missing": [f for f in ("skill", "perk", "var_keys")
                            if not (f == "skill" and skill)
                                or (f == "perk" and perk)
                                or (f == "var_keys" and var_keys_raw)],
            }

        var_keys = set(var_keys_raw) if isinstance(var_keys_raw, list) else set(var_keys_raw)
        band = data.get("band", self.default_band)

        # Sanitize the request before audit (never log secrets)
        sanitized = sanitize_dict(data)

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
