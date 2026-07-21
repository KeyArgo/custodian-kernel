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
from collections import defaultdict, deque
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint("stripe_webhook", __name__)

LEDGER = Path(__file__).resolve().parents[2] / "skills" / "earnings" / "hermes-earn-ledger.json"
LEDGER_LOCK = LEDGER.parent / "hermes-earn-ledger.lock"
# Repo-relative demo ledger (created on first write, see _append). Production:
# point HERMES_EARN_LEDGER at a persistent path outside the checkout.


@contextmanager
def _process_lock():
    """Serialize the dedup-check-then-append sequence across processes.

    Without this, two near-simultaneous webhook deliveries for the same
    Stripe event (Stripe itself retries on a slow response) could both read
    the ledger, both see no existing stripe_id, and both append -- double-
    crediting revenue in the publicly-displayed P&L total. Same cross-
    platform locking pattern as custodian/codex_guard/receipts.py.
    """
    LEDGER_LOCK.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(LEDGER_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    stream = os.fdopen(fd, "r+b", buffering=0)
    try:
        if os.name == "nt":
            import msvcrt
            if LEDGER_LOCK.stat().st_size == 0:
                stream.write(b"0")
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

# Independent rate-limit bucket from the other public dashboard endpoints --
# a flood on one shouldn't silently starve another's budget for the same
# visitor. Same pattern as nemotron_chat.py/playground.py.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 30
_request_log: dict = defaultdict(deque)


def _client_ip() -> str:
    """CF-Connecting-IP is client-supplied input -- trusting it
    unconditionally lets a client rotate the header value per request to
    get a fresh rate-limit bucket every time. Only honored when the
    operator has explicitly confirmed a trusted proxy terminates every
    path to this process (TRUSTED_PROXY_HEADER=CF-Connecting-IP); otherwise
    falls back to request.remote_addr, which a client cannot forge. Same
    fix applied to nemotron_chat.py/playground.py this session."""
    if os.environ.get("TRUSTED_PROXY_HEADER") == "CF-Connecting-IP":
        return request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"
    return request.remote_addr or "unknown"


def rate_limited(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = _client_ip()
        now = time.time()
        log = _request_log[ip]
        while log and now - log[0] > _RATE_LIMIT_WINDOW_SECONDS:
            log.popleft()
        if len(log) >= _RATE_LIMIT_MAX_REQUESTS:
            return jsonify({
                "error": f"Rate limit exceeded -- max {_RATE_LIMIT_MAX_REQUESTS} requests per "
                         f"{_RATE_LIMIT_WINDOW_SECONDS}s per IP on this demo endpoint.",
            }), 429
        log.append(now)
        return f(*args, **kwargs)
    return wrapper


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
@rate_limited
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


_WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300  # Stripe's own recommended tolerance


@bp.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig = request.headers.get("Stripe-Signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not secret:
        return jsonify({"error": "webhook secret not configured — rejecting unverifiable event"}), 500

    # Signature verification alone is not anti-replay: a captured, genuinely
    # valid (payload, signature) pair passed this check every time it was
    # resent, with no bound on how many times or how long after the fact.
    # Two independent guards close this, matching Stripe's own recommended
    # practice: (1) reject a signature whose timestamp has aged out of a
    # reasonable tolerance -- closes off replaying an intercepted request
    # long after the fact; (2) de-duplicate by the event's own Stripe id --
    # closes off both a replay within that window and Stripe's own ordinary
    # retries (which legitimately resend the identical event on a timeout).
    # Verified live: 5 identical webhook deliveries used to append 5 ledger
    # entries and credit 5x the real amount -- pnl.py's publicly-displayed
    # total_earned/margin_pct sum this same file. Found in review.
    try:
        parts = {p.split("=")[0]: p.split("=")[1] for p in sig.split(",") if "=" in p}
        ts = parts.get("t", "0")
        v1 = parts.get("v1", "")
        signed = f"{ts}.".encode() + payload
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, v1):
            return jsonify({"error": "invalid signature"}), 400
        if abs(time.time() - float(ts)) > _WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS:
            return jsonify({"error": "signature timestamp outside tolerance"}), 400
    except Exception:
        return jsonify({"error": "signature check failed"}), 400

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return jsonify({"error": "invalid json"}), 400

    if event.get("type") == "payment_intent.succeeded":
        pi = event.get("data", {}).get("object", {})
        stripe_id = pi.get("id", "")
        with _process_lock():
            already_processed = bool(stripe_id) and any(
                e.get("stripe_id") == stripe_id for e in _read_all()
            )
            if not already_processed:
                amount_cents = pi.get("amount", 0)
                entry = {
                    "ts": time.time(),
                    "event": "earned",
                    "amount": round(amount_cents / 100, 2),
                    "currency": pi.get("currency", "usd"),
                    "description": pi.get("description") or "Stripe payment",
                    "stripe_id": stripe_id,
                    "source": "stripe_webhook",
                }
                _append(entry)

    return jsonify({"received": True}), 200


@bp.route("/ledger", methods=["GET"])
def ledger():
    events = _read_all()
    total = round(sum(e.get("amount", 0) for e in events), 2)
    return jsonify({"events": events, "total_earned": total, "count": len(events)}), 200
