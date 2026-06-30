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
                 state_dir: Optional[str] = None, default_band: str = "L2"):
        self.app = app
        self.policy_path = policy
        self.state_dir = state_dir
        self.default_band = default_band
        self._governed_paths: dict = {}

    def register_path(self, path: str, band: str = "L2", cap: float = 10.00):
        """Register a route as governed. Returns self for chaining."""
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
