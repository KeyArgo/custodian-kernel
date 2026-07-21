"""Regression 2026-07-21: POST /api/v1/triage/custom (the Lie-Catch/Triage
"write your own message" box) called float() on the payload's `amount`
field with no try/except, unlike every other money-accepting route in this
codebase. A non-numeric amount ("not-a-number", "", etc.) raised an
uncaught ValueError and Flask returned a raw 500 HTML error page to the
visitor instead of a clean validation error -- reproduced live via the
Flask test client before the fix.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client():
    from app import app
    return app.test_client()


@pytest.mark.parametrize("bad_amount", ["not-a-number", "NaN", "inf", "-5"])
def test_custom_rejects_non_numeric_amount_with_400_not_500(client, bad_amount):
    resp = client.post("/api/v1/triage/custom", json={
        "pack": "refunds",
        "customer_email": "it never arrived",
        "amount": bad_amount,
    })
    assert resp.status_code == 400
    assert resp.get_json().get("error")


def test_custom_still_accepts_a_valid_numeric_amount(client):
    resp = client.post("/api/v1/triage/custom", json={
        "pack": "refunds",
        "customer_email": "it never arrived, please refund me",
        "amount": "42.50",
    })
    assert resp.status_code == 200


def test_custom_works_with_no_amount_at_all(client):
    resp = client.post("/api/v1/triage/custom", json={
        "pack": "refunds",
        "customer_email": "it never arrived, please refund me",
    })
    assert resp.status_code == 200


def test_custom_treats_empty_string_amount_same_as_missing(client):
    """`amount: ""` (e.g. an empty form field) is falsy, same as an absent
    key -- payload.get("amount") or sandbox["amount"] intentionally falls
    back to the sandbox default rather than erroring. Documented here so
    it reads as intentional, not an accidental gap next to the ValueError
    guard above."""
    resp = client.post("/api/v1/triage/custom", json={
        "pack": "refunds",
        "customer_email": "it never arrived, please refund me",
        "amount": "",
    })
    assert resp.status_code == 200
