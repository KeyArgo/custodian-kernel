"""Captured-mode triage endpoint — no API key required.

Judges and visitors can run the full Custodian triage pipeline against any
corpus case using stored (captured) Nemotron envelopes, with zero external
API dependency. Every result is labelled 'captured' so it is never passed off
as a fresh model call.

Two routes:
  GET  /api/v1/triage/health  — health check + corpus case count
  POST /api/v1/triage/live    — captured triage for a customer/order pair
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custodian.packs.base import Envelope, verify_claims
from custodian.packs.engine import triage
from custodian.packs.refunds.pack import RefundPack
from custodian.policy.loader import load_policy
from custodian.types import AuthorityState, Band

bp = Blueprint("triage_live", __name__)

_HERE = Path(__file__).resolve().parent
_CORPUS_DIR = _HERE.parent.parent / "custodian" / "packs" / "refunds" / "corpus"
_KERNEL_POLICY = _HERE.parent.parent / "custodian" / "packs" / "refunds" / "policy.yaml"
_DEFAULT_CASE = "06-planted-lie"

_STATE = lambda: AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=1000.0)


def _load_corpus() -> dict[str, dict]:
    """Load all corpus fixtures keyed by (customer_id, order_id)."""
    index: dict[tuple[str, str], dict] = {}
    for path in sorted(_CORPUS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            env = data.get("envelope", {})
            key = (env.get("customer_id", ""), env.get("order_id", ""))
            index[key] = data
        except (json.JSONDecodeError, KeyError):
            continue
    return index


def _corpus_count() -> int:
    return len(list(_CORPUS_DIR.glob("*.json")))


def _default_fixture() -> dict:
    return json.loads((_CORPUS_DIR / f"{_DEFAULT_CASE}.json").read_text())


@bp.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "captured_cases": _corpus_count()})


@bp.route("/live", methods=["POST"])
def live():
    """Run captured triage — no Nemotron API key required.

    Body: {"email": str, "customer_id": str, "order_id": str, "amount": float}

    Finds the stored corpus fixture whose envelope matches (customer_id, order_id).
    Falls back to the planted-lie demo case (06-planted-lie) if not found.
    Returns the full TriageResult panel, extended with adapter fields.
    """
    payload = request.get_json(force=True, silent=True) or {}
    customer_id = str(payload.get("customer_id") or "").strip()
    order_id = str(payload.get("order_id") or "").strip()

    try:
        amount = float(payload.get("amount") or 0) or None
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    # float("nan")/float("inf") both parse successfully and are truthy (NaN
    # is truthy in Python), so they weren't caught by the `or None` above --
    # they flowed straight into envelope_dict["amount"] and were serialized
    # as literal NaN/Infinity tokens, which is not valid JSON per RFC 8259
    # and throws in any strict client (e.g. browser fetch().json()).
    if amount is not None and not math.isfinite(amount):
        return jsonify({"error": "amount must be a finite number"}), 400

    # Look up matching fixture; fall back to default demo case.
    corpus = _load_corpus()
    data = corpus.get((customer_id, order_id)) or _default_fixture()

    envelope_dict = dict(data["envelope"])
    if amount:
        envelope_dict["amount"] = amount

    envelope = Envelope.from_dict(envelope_dict)

    pack = RefundPack()
    try:
        kernel_policy = load_policy(_KERNEL_POLICY)
    except (FileNotFoundError, Exception):
        # Minimal fallback policy that always requires approval for refunds
        from custodian.policy.loader import parse_policy
        kernel_policy = parse_policy({
            "version": "1.0",
            "default_band": "L3",
            "bands": {
                "L3": {"max_spend": 500.0, "requires_approval": True, "approval_backend": "twilio_verify"},
            },
            "rules": [],
            "escalation": {"timeout_seconds": 600, "on_timeout": "deny", "retry_count": 0},
        })

    result = triage(pack, envelope, kernel_policy, _STATE())
    panel = result.to_panel()

    # Extend with adapter fields and honesty labels
    panel["pack"] = "refunds"
    panel["customer_email"] = payload.get("email") or data.get("customer_email", "")
    panel["title"] = data.get("title", envelope.case_id)
    panel["expected_disposition"] = data.get("expect")
    panel["envelope_source"] = "captured agent output"
    panel["is_captured"] = True
    panel["model_used"] = "captured (no live API key required)"
    panel["overrode_agent"] = panel["adapter_disposition"] != panel["agent_recommended"]

    return jsonify(panel)
