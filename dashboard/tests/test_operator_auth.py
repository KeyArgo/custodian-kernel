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
    ("get", "/api/v1/operator/pending_code"),
    ("post", "/api/v1/operator/forward_code"),
    ("post", "/api/v1/operator/spark/disable"),
    ("post", "/api/v1/operator/spark/enable"),
    ("get", "/api/v1/operator/sandbox/status"),
    ("post", "/api/v1/enforcement-mode"),
])
def test_privileged_routes_reject_missing_operator_token(client, method, path):
    response = getattr(client, method)(path, json={})
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


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
