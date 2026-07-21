"""Operator control-plane routes must never be reachable anonymously."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client():
    from app import app
    return app.test_client()


@pytest.mark.parametrize(("method", "path"), [
    ("post", "/api/v1/operator/earn"),
    ("post", "/api/v1/operator/spend"),
    ("post", "/api/v1/operator/refund"),
    ("post", "/api/v1/operator/approve"),
    ("post", "/api/v1/operator/kill"),
    ("post", "/api/v1/operator/resume"),
    ("post", "/api/v1/operator/spark/disable"),
    ("post", "/api/v1/operator/spark/enable"),
    ("get", "/api/v1/operator/sandbox/status"),
    ("post", "/api/v1/enforcement-mode"),
])
def test_privileged_routes_reject_missing_operator_token(client, method, path):
    response = getattr(client, method)(path, json={})
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/api/v1/operator/pending_code"),
    ("post", "/api/v1/operator/forward_code"),
])
def test_public_demo_arc_routes_do_not_require_operator_token(client, method, path):
    """pending_code and forward_code are the deliberate exception: the whole
    demo arc except /reset is intentionally reachable by an anonymous
    visitor (Steps 3 and 8). Each has its own rate limit instead of an auth
    gate -- forward_code costs real money per call (a Twilio send)."""
    response = getattr(client, method)(path, json={})
    assert response.status_code != 401


def test_forward_code_is_rate_limited_per_ip(client, monkeypatch):
    import collections
    import api.operator as operator
    monkeypatch.setattr(operator, "_sms_rate", collections.defaultdict(list))
    for _ in range(operator._SMS_LIMIT):
        r = client.post("/api/v1/operator/forward_code",
                        json={"phone": "5551234567", "code": "123456"})
        assert r.status_code != 429
    r = client.post("/api/v1/operator/forward_code",
                    json={"phone": "5551234567", "code": "123456"})
    assert r.status_code == 429


def test_pending_code_is_rate_limited_per_ip(client, monkeypatch):
    import collections
    import api.operator as operator
    monkeypatch.setattr(operator, "_pending_code_rate", collections.defaultdict(list))
    for _ in range(operator._PENDING_CODE_LIMIT):
        r = client.get("/api/v1/operator/pending_code")
        assert r.status_code != 429
    r = client.get("/api/v1/operator/pending_code")
    assert r.status_code == 429


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_operator_money_routes_reject_nonfinite_amounts(client, monkeypatch, amount):
    import api.operator as operator
    monkeypatch.setattr(operator, "_token_valid", lambda token: token == "valid")
    for path in ("earn", "spend", "refund"):
        response = client.post(
            f"/api/v1/operator/{path}", json={"amount": amount},
            headers={"X-Operator-Token": "valid"},
        )
        assert response.status_code == 400


def test_require_operator_logs_internal_errors_instead_of_swallowing_them(client, monkeypatch, caplog):
    """A bug inside _token_valid itself (e.g. a corrupted secrets file) must
    still fail closed (401), but must not look identical in the logs to an
    ordinary wrong-token request -- that hid real errors from debugging."""
    import api.operator as operator

    def _boom(token):
        raise RuntimeError("secrets file is corrupted")

    monkeypatch.setattr(operator, "_token_valid", _boom)
    with caplog.at_level("ERROR"):
        response = client.post(
            "/api/v1/operator/earn", json={},
            headers={"X-Operator-Token": "anything"},
        )
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}
    assert any("_token_valid raised" in r.message for r in caplog.records)
