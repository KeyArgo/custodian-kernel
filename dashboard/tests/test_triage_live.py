"""Tests for the captured triage endpoints (triage_live blueprint).

These run against a real Flask test client — no mocking of the triage engine,
no mocking of file I/O. The corpus fixtures and account ledger ship with the
repo, so these tests pass on any checkout with no external dependencies.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # dashboard/, for `import app`


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        r = client.get("/api/v1/triage/health")
        assert r.status_code == 200

    def test_health_ok_is_true(self, client):
        data = client.get("/api/v1/triage/health").get_json()
        assert data["ok"] is True

    def test_health_includes_captured_cases(self, client):
        data = client.get("/api/v1/triage/health").get_json()
        assert isinstance(data["captured_cases"], int)
        assert data["captured_cases"] >= 6


class TestLiveEndpoint:
    def test_known_case_returns_planted_lie_case_id(self, client):
        r = client.post(
            "/api/v1/triage/live",
            json={"customer_id": "cus_marcus", "order_id": "ord_6006"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["case_id"] == "06-planted-lie"

    def test_planted_lie_has_contradiction(self, client):
        r = client.post(
            "/api/v1/triage/live",
            json={"customer_id": "cus_marcus", "order_id": "ord_6006"},
        )
        data = r.get_json()
        assert data["contradiction_count"] >= 1

    def test_planted_lie_adapter_flags_abuse(self, client):
        r = client.post(
            "/api/v1/triage/live",
            json={"customer_id": "cus_marcus", "order_id": "ord_6006"},
        )
        data = r.get_json()
        assert data["adapter_disposition"] == "flag_abuse"

    def test_unknown_customer_falls_back_to_demo_case(self, client):
        r = client.post(
            "/api/v1/triage/live",
            json={"customer_id": "cus_nobody", "order_id": "ord_0000"},
        )
        assert r.status_code == 200
        data = r.get_json()
        # Falls back to the demo (planted lie) case
        assert data["case_id"] == "06-planted-lie"

    def test_response_includes_adapter_disposition(self, client):
        r = client.post("/api/v1/triage/live", json={})
        data = r.get_json()
        assert "adapter_disposition" in data

    def test_response_is_captured_and_labelled(self, client):
        r = client.post("/api/v1/triage/live", json={})
        data = r.get_json()
        assert data.get("is_captured") is True
        assert "captured" in data.get("model_used", "").lower()

    def test_amount_field_present_in_response(self, client):
        r = client.post(
            "/api/v1/triage/live",
            json={"customer_id": "cus_marcus", "order_id": "ord_6006", "amount": 42.0},
        )
        data = r.get_json()
        assert data["amount"] == 42.0

    def test_clean_case_approve_not_flagged(self, client):
        r = client.post(
            "/api/v1/triage/live",
            json={"customer_id": "cus_amara", "order_id": "ord_1001"},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["contradiction_count"] == 0
        assert data["adapter_disposition"] == "approve_recommended"
