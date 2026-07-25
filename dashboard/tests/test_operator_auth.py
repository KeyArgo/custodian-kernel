"""The operator demo arc is public; only /reset keeps a password gate."""
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
    ("get", "/api/v1/operator/spark/status"),
    ("get", "/api/v1/operator/sandbox/status"),
    ("post", "/api/v1/enforcement-mode"),
    ("get", "/api/v1/operator/pending_code"),
    ("post", "/api/v1/operator/forward_code"),
])
def test_public_demo_arc_routes_do_not_require_operator_token(client, method, path):
    """The whole demo arc, plus the Spark/enforcement-mode infra toggles, is
    intentionally reachable by an anonymous visitor -- no operator token or
    password required. Abuse is bounded by per-IP rate limits on the routes
    that cost real money (forward_code) rather than by an auth gate."""
    response = getattr(client, method)(path, json={})
    assert response.status_code != 401


def test_reset_rejects_missing_password_or_token(client):
    response = client.post("/api/v1/operator/reset", json={})
    assert response.status_code in (401, 503)


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
def test_operator_money_routes_reject_nonfinite_amounts(client, amount):
    for path in ("earn", "spend", "refund"):
        response = client.post(
            f"/api/v1/operator/{path}", json={"amount": amount},
        )
        assert response.status_code == 400
