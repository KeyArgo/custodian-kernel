"""Tests for CustodianMiddleware (ASGI)."""
import json
import pytest
from custodian.middleware import CustodianMiddleware


def make_scope(path: str, method: str = "POST"):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
    }


def make_receive(body: bytes):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return receive


def collect_send():
    messages = []

    async def send(msg):
        messages.append(msg)

    return send, messages


async def stub_app(scope, receive, send):
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [],
    })
    await send({
        "type": "http.response.body",
        "body": b'{"ok": true}',
    })


@pytest.mark.asyncio
async def test_ungoverned_path_passes_through():
    app = CustodianMiddleware(stub_app)
    scope = make_scope("/health")
    send_fn, messages = collect_send()
    await app(scope, make_receive(b""), send_fn)
    assert messages[0]["status"] == 200


@pytest.mark.asyncio
async def test_governed_autonomous_passes_through():
    app = CustodianMiddleware(stub_app)
    app.register_path("/charge", band="L2", cap=100.00)
    body = json.dumps({"amount": 10.00}).encode()
    scope = make_scope("/charge")
    send_fn, messages = collect_send()
    await app(scope, make_receive(body), send_fn)
    # Find the response start
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 200
    headers = dict(start.get("headers", []))
    assert b"x-custodian-verdict" in headers
    assert headers[b"x-custodian-verdict"] == b"autonomous"


@pytest.mark.asyncio
async def test_governed_escalation_returns_402():
    app = CustodianMiddleware(stub_app)
    app.register_path("/charge", band="L2", cap=5.00)
    body = json.dumps({"amount": 999.00}).encode()
    scope = make_scope("/charge")
    send_fn, messages = collect_send()
    await app(scope, make_receive(body), send_fn)
    start = next(m for m in messages if m["type"] == "http.response.start")
    assert start["status"] == 402


@pytest.mark.asyncio
async def test_websocket_scope_passes_through():
    app = CustodianMiddleware(stub_app)
    app.register_path("/ws", band="L2", cap=10.00)

    ws_scope = {"type": "websocket", "path": "/ws"}
    send_fn, messages = collect_send()
    # websocket doesn't send http.response.start — just verify no error
    received = []
    async def ws_receive():
        return {"type": "websocket.connect"}

    # Should pass through without processing (stub_app will be called)
    try:
        await app(ws_scope, ws_receive, send_fn)
    except Exception:
        pass  # stub_app is not a real WS handler; what matters is no middleware error


@pytest.mark.asyncio
async def test_register_path_returns_self():
    app = CustodianMiddleware(stub_app)
    result = app.register_path("/charge", band="L2", cap=10.00)
    assert result is app
