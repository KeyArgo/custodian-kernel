"""Stripe earn-loop endpoints.

POST /demo-earn  — trigger a test earn event (demo/camera use)
POST /webhook   — real Stripe webhook (payment_intent.succeeded)
GET  /ledger    — all earn events + total
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint("stripe_webhook", __name__)

LEDGER = Path(__file__).resolve().parents[2] / "skills" / "earnings" / "hermes-earn-ledger.json"
# Repo-relative demo ledger (created on first write, see _append). Production:
# point HERMES_EARN_LEDGER at a persistent path outside the checkout.


def _append(entry: dict) -> None:
    # Create the parent dir first: skills/earnings/ does not exist in a fresh
    # checkout, so append-mode open() raised FileNotFoundError and any visitor
    # hitting the public /demo-earn or /webhook route got an uncaught 500.
    # _read_all already guards with .exists(); this makes the write symmetric.
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def _read_all() -> list[dict]:
    if not LEDGER.exists():
        return []
    events = []
    for line in LEDGER.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


@bp.route("/demo-earn", methods=["POST"])
def demo_earn():
    body = request.get_json(silent=True) or {}
    try:
        amount = float(body.get("amount", 25.00))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    if amount <= 0 or amount > 10_000:
        return jsonify({"error": "amount must be between 0 and 10000"}), 400
    description = str(body.get("description", "Customer payment for AI service"))[:200]
    entry = {
        "ts": time.time(),
        "event": "earned",
        "amount": round(amount, 2),
        "currency": "usd",
        "description": description,
        "stripe_id": f"demo_{int(time.time())}",
        "source": "demo",
    }
    _append(entry)
    return jsonify(entry), 200


@bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not secret:
        return jsonify({"error": "webhook secret not configured — rejecting unverifiable event"}), 500

    try:
        parts = {p.split("=")[0]: p.split("=")[1] for p in sig.split(",") if "=" in p}
        ts = parts.get("t", "0")
        v1 = parts.get("v1", "")
        signed = f"{ts}.".encode() + payload
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, v1):
            return jsonify({"error": "invalid signature"}), 400
    except Exception:
        return jsonify({"error": "signature check failed"}), 400

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return jsonify({"error": "invalid json"}), 400

    if event.get("type") == "payment_intent.succeeded":
        pi = event.get("data", {}).get("object", {})
        amount_cents = pi.get("amount", 0)
        entry = {
            "ts": time.time(),
            "event": "earned",
            "amount": round(amount_cents / 100, 2),
            "currency": pi.get("currency", "usd"),
            "description": pi.get("description") or "Stripe payment",
            "stripe_id": pi.get("id", ""),
            "source": "stripe_webhook",
        }
        _append(entry)

    return jsonify({"received": True}), 200


@bp.route("/ledger", methods=["GET"])
def ledger():
    events = _read_all()
    total = round(sum(e.get("amount", 0) for e in events), 2)
    return jsonify({"events": events, "total_earned": total, "count": len(events)}), 200
