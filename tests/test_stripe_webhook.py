"""Tests for dashboard/api/stripe_webhook.py.

No test coverage existed for this route before this session's adversarial
review found a real replay-attack bug: signature verification was correct,
but the same valid (payload, signature) pair could be replayed any number
of times and was appended to the ledger every time, with no bound on
elapsed time either. pnl.py's publicly-displayed total_earned sums this
same ledger file.
"""
import hashlib
import hmac
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dashboard"))

flask = pytest.importorskip("flask")

SECRET = "whsec_test_secret"


def _sign(payload: bytes, secret: str = SECRET, ts=None) -> str:
    ts = str(int(ts if ts is not None else time.time()))
    signed = f"{ts}.".encode() + payload
    v1 = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={v1}"


def _event(stripe_id="pi_real_charge_001", amount=50000):
    return json.dumps({
        "type": "payment_intent.succeeded",
        "data": {"object": {
            "id": stripe_id, "amount": amount, "currency": "usd",
            "description": "test charge",
        }},
    }).encode()


@pytest.fixture
def app(tmp_path, monkeypatch):
    import dashboard.api.stripe_webhook as webhook_module
    monkeypatch.setattr(webhook_module, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr(webhook_module, "LEDGER_LOCK", tmp_path / "ledger.lock")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)

    from flask import Flask
    flask_app = Flask(__name__)
    flask_app.register_blueprint(webhook_module.bp, url_prefix="/api/v1/stripe")
    return flask_app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def test_valid_webhook_is_recorded(client):
    payload = _event()
    r = client.post("/api/v1/stripe/webhook", data=payload,
                    headers={"Stripe-Signature": _sign(payload)})
    assert r.status_code == 200

    events = client.get("/api/v1/stripe/ledger").get_json()
    assert events["count"] == 1
    assert events["total_earned"] == 500.0


def test_tampered_payload_is_rejected(client):
    payload = _event()
    sig = _sign(payload)  # sign the ORIGINAL payload
    tampered = _event(amount=99999900)  # then send a different one
    r = client.post("/api/v1/stripe/webhook", data=tampered,
                    headers={"Stripe-Signature": sig})
    assert r.status_code == 400

    events = client.get("/api/v1/stripe/ledger").get_json()
    assert events["count"] == 0


def test_replayed_webhook_is_not_double_credited(client):
    """The core bug: signature verification alone is not anti-replay. The
    identical, validly-signed event resent 5 times must be credited once,
    not 5 times."""
    payload = _event()
    sig = _sign(payload)

    for _ in range(5):
        r = client.post("/api/v1/stripe/webhook", data=payload,
                        headers={"Stripe-Signature": sig})
        assert r.status_code == 200  # Stripe expects a 2xx even on a dupe

    events = client.get("/api/v1/stripe/ledger").get_json()
    assert events["count"] == 1
    assert events["total_earned"] == 500.0


def test_concurrent_delivery_of_the_same_event_is_not_double_credited(app, client):
    """The narrower TOCTOU bug: the dedup check reads the whole ledger,
    then appends, with no lock between the two -- two near-simultaneous
    deliveries of the *same* event (Stripe does retry on a slow response)
    could both pass the check before either writes, double-crediting
    revenue. Unlike test_replayed_webhook_is_not_double_credited above
    (sequential replays), this fires genuinely concurrent requests, each
    through its own test client (Flask's test client is not safe to share
    across threads)."""
    payload = _event()
    sig = _sign(payload)

    def _post():
        with app.test_client() as c:
            return c.post("/api/v1/stripe/webhook", data=payload,
                          headers={"Stripe-Signature": sig}).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: _post(), range(8)))

    assert all(s == 200 for s in statuses)
    events = client.get("/api/v1/stripe/ledger").get_json()
    assert events["count"] == 1
    assert events["total_earned"] == 500.0


def test_different_events_are_both_recorded(client):
    """De-duplication must be per-event-id, not a blanket "only one ever"."""
    p1 = _event(stripe_id="pi_one", amount=1000)
    p2 = _event(stripe_id="pi_two", amount=2000)
    client.post("/api/v1/stripe/webhook", data=p1, headers={"Stripe-Signature": _sign(p1)})
    client.post("/api/v1/stripe/webhook", data=p2, headers={"Stripe-Signature": _sign(p2)})

    events = client.get("/api/v1/stripe/ledger").get_json()
    assert events["count"] == 2


def test_old_timestamp_is_rejected(client):
    payload = _event()
    old_sig = _sign(payload, ts=time.time() - 3600)  # signed correctly, but an hour old
    r = client.post("/api/v1/stripe/webhook", data=payload,
                    headers={"Stripe-Signature": old_sig})
    assert r.status_code == 400
    assert "tolerance" in r.get_json()["error"]


def test_demo_earn_is_rate_limited(client):
    for _ in range(30):
        r = client.post("/api/v1/stripe/demo-earn", json={"amount": 1.0})
        assert r.status_code == 200
    r = client.post("/api/v1/stripe/demo-earn", json={"amount": 1.0})
    assert r.status_code == 429
