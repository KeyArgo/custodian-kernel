"""P&L summary endpoint — earn vs spend, net, margin.

Delegates to hermes.py for all audit-log reads so both use the same
HERMES_SKILL_STATE_PATH — otherwise pnl.py resolves skill paths relative
to its own location (dashboard/) and reads a dead directory.

GET /api/v1/pnl/summary
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from flask import Blueprint, jsonify

import api.hermes as hermes

bp = Blueprint("pnl", __name__)

# Demo earn ledger: mirrors the path stripe_webhook.py writes to.
# stripe_webhook.py uses skills/earnings/ relative to the repo root.
# In production the repo root is under the sandbox mount.
_SKILL_STATE = Path(os.environ.get(
    'HERMES_SKILL_STATE_PATH',
    '/tmp/hermes-mount/sandbox/.hermes/skills/payments/stripe-spend/state',
))
DEMO_EARN_LEDGER = Path(
    os.environ.get(
        'HERMES_EARN_LEDGER',
        str(_SKILL_STATE.parents[2] / "earnings" / "hermes-earn-ledger.json"),
    )
)


def _get_audit_log() -> list[dict]:
    """Read audit log via hermes.py which resolves the correct SANDBOX path."""
    return hermes.get_audit_log(limit=200)


def _read_jsonl(p: Path) -> list[dict]:
    """Read a JSONL file, skipping invalid lines."""
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
