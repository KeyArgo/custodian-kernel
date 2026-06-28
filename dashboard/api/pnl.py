"""P&L summary endpoint — earn vs spend, net, margin.

Reads from the real skill audit log (skills/payments/stripe-spend/state/audit_log.jsonl)
plus the demo earn ledger (/tmp/hermes-earn-ledger.json).

GET /api/v1/pnl/summary
"""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint("pnl", __name__)

# Real skill audit log (relative to this file's location in dashboard/api/)
_HERE = Path(__file__).resolve().parent.parent  # dashboard/
SKILL_LOG = _HERE.parent / "skills" / "payments" / "stripe-spend" / "state" / "audit_log.jsonl"

# Demo earn ledger (written by stripe_webhook.py demo-earn endpoint)
DEMO_EARN_LEDGER = Path("/tmp/hermes-earn-ledger.json")

# Also check server-side path for when running from /tmp/hermes-dash-v4/
SERVER_SKILL_LOG = Path("/tmp/hermes-dash-v4/skills/payments/stripe-spend/state/audit_log.jsonl")


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    events = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def _get_audit_log() -> list[dict]:
    for p in [SKILL_LOG, SERVER_SKILL_LOG]:
        events = _read_jsonl(p)
        if events:
            return events
    return []


@bp.route("/summary", methods=["GET"])
def summary():
    audit = _get_audit_log()
    demo = _read_jsonl(DEMO_EARN_LEDGER)

    # Earn events from real audit log
    real_earns = [e for e in audit if e.get("event") in ("earn", "earned")]
    # Earn events from demo endpoint
    demo_earns = demo  # all entries in demo ledger are earn events

    # Spend events — executed autonomously or approved
    spend_events = [
        e for e in audit
        if e.get("event") in ("spend", "executed", "approved", "spend_approved")
        and e.get("amount") is not None
    ]

    total_earned = round(
        sum(e.get("amount", 0) for e in real_earns) +
        sum(e.get("amount", 0) for e in demo_earns),
        2
    )
    total_spent = round(sum(e.get("amount", 0) for e in spend_events), 2)
    net = round(total_earned - total_spent, 2)
    margin = round((net / total_earned * 100), 1) if total_earned > 0 else 0.0

    return jsonify({
        "earned": total_earned,
        "spent": total_spent,
        "net": net,
        "held": 0.0,
        "earn_events": len(real_earns) + len(demo_earns),
        "spend_events": len(spend_events),
        "margin_pct": margin,
    }), 200
