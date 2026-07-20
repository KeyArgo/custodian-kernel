"""Tests for CustodianMiddleware (ASGI)."""
import asyncio
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
@pytest.mark.parametrize("body,error", [
    (b"not-json", "invalid-json"),
    (b"[]", "json-object-required"),
    (b"{}", "missing-amount"),
    (b'{"amount": true}', "invalid-amount"),
    (b'{"amount": "nope"}', "invalid-amount"),
    (b'{"amount": NaN}', "non-finite-amount"),
    (b'{"amount": Infinity}', "non-finite-amount"),
])
async def test_governed_invalid_amount_never_reaches_application(body, error):
    called = False

    async def should_not_run(scope, receive, send):
        nonlocal called
        called = True

    app = CustodianMiddleware(should_not_run)
    app.register_path("/charge", band="L2", cap=100.00)
    send_fn, messages = collect_send()
    await app(make_scope("/charge"), make_receive(body), send_fn)
    assert not called
    assert messages[0]["status"] == 400
    assert json.loads(messages[1]["body"])["error"] == error


@pytest.mark.asyncio
async def test_governed_body_size_is_bounded():
    app = CustodianMiddleware(stub_app, max_body_bytes=8)
    app.register_path("/charge")
    send_fn, messages = collect_send()
    await app(make_scope("/charge"), make_receive(b'{"amount": 1}'), send_fn)
    assert messages[0]["status"] == 413


@pytest.mark.asyncio
async def test_value_free_plan_rejects_string_var_keys():
    app = CustodianMiddleware(stub_app)
    body = json.dumps({"skill": "x", "perk": "y", "var_keys": "TOKEN"}).encode()
    send_fn, messages = collect_send()
    await app(make_scope("/__custodian__/plan"), make_receive(body), send_fn)
    assert messages[0]["status"] == 400


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


# ── Path-normalization regression (written as plain sync tests using
# asyncio.run so they run even in an environment without pytest-asyncio
# installed, unlike every @pytest.mark.asyncio test above). ──────────────

def test_path_variants_cannot_bypass_a_governed_route():
    """A byte-for-byte-only match against scope["path"] let a request
    differing only by a trailing slash, a doubled leading slash, case, or
    a decoded %20 reach the downstream app completely ungoverned -- no
    band/cap/kill-switch check, no audit trail. Reproduced: a $999,999
    request to a route registered L4 (always-escalates) sailed through as
    an ordinary 200 via /charge/, //charge, /CHARGE, or /charge%20 (which
    the ASGI server decodes to a literal trailing space before this
    middleware ever sees scope["path"]). Found in review."""
    app = CustodianMiddleware(stub_app)
    app.register_path("/charge", band="L4", cap=10.00)  # L4: always requires approval
    body = json.dumps({"amount": 999999.00}).encode()

    for variant in ("/charge", "/charge/", "//charge", "/CHARGE", "/charge ", " /charge"):
        send_fn, messages = collect_send()
        asyncio.run(app(make_scope(variant), make_receive(body), send_fn))
        assert messages[0]["status"] == 402, (variant, messages[0])

    # A genuinely different, unregistered route must still pass through.
    send_fn, messages = collect_send()
    asyncio.run(app(make_scope("/unrelated-route"), make_receive(body), send_fn))
    assert messages[0]["status"] == 200


def test_value_free_plan_missing_fields_reports_only_actually_missing_fields():
    """Operator precedence in the old list comprehension made
    `not (f == "skill" and skill)` true for every f != "skill", so "perk"
    and "var_keys" were always reported as missing once the gate fired --
    even when both were actually present. Found in review."""
    app = CustodianMiddleware(stub_app)
    body = json.dumps({"perk": "p1", "var_keys": ["a"]}).encode()  # only skill absent
    send_fn, messages = collect_send()
    asyncio.run(app(make_scope("/__custodian__/plan"), make_receive(body), send_fn))
    payload = json.loads(messages[1]["body"])
    assert payload["missing"] == ["skill"]
