"""Minimal Custodian enforcement microservice — runs on DGX Spark.

Exposes one endpoint: POST /decide
argobox-lite calls this with a spend request + state + policy.
If unreachable (timeout / network), argobox-lite enforces locally.

The Spark is the primary trust anchor. argobox-lite is the fallback.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from flask import Flask, jsonify, request as flask_request

# custodian package must be on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custodian.policy.evaluator import decide
from custodian.policy.enforcer import _requires_local_enforcement
from custodian.policy.loader import load_policy
from custodian.policy.schema import Policy
from custodian.types import AuthorityState, SpendRequest

app = Flask(__name__)

_POLICY_PATH = Path(__file__).parent / 'policy.yaml'
_DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / 'custodian' / 'policy' / 'presets' / 'default.yaml'

_policy: Policy | None = None


def _load_policy() -> Policy:
    # Policy.from_dict()/Policy.default() were called here but neither
    # exists anywhere on custodian.policy.schema.Policy -- every real
    # /decide call crashed with AttributeError before this fix. The client
    # (custodian/policy/enforcer.py's _try_spark_node) happened to treat
    # that crash's malformed error response as "node unreachable" and fall
    # back to local enforcement, so this was masked rather than exploited
    # -- but a broken remote trust anchor that fails by accident, not by
    # design, is not something to leave in place. Found in review.
    global _policy
    if _policy is None:
        path = _POLICY_PATH if _POLICY_PATH.exists() else _DEFAULT_POLICY_PATH
        _policy = load_policy(path)
    return _policy


@app.get('/health')
def health():
    return jsonify({'ok': True, 'node': 'dgx-spark', 'role': 'enforcement-primary'})


@app.post('/decide')
def decide_endpoint():
    body = flask_request.get_json(force=True, silent=True) or {}
    try:
        policy = _load_policy()
        # This node's own local policy -- not visibility into what the
        # client thinks it's sending -- is the only thing that determines
        # whether margins/daily_envelope/no_self_dealing apply here. Those
        # gates need inputs (revenue, cost, requester_agent_id, a 24h
        # ledger) this HTTP endpoint has no way to independently verify;
        # SpendRequest(**body['request']) unpacks them straight from an
        # unauthenticated request body. Evaluating a self-dealing/margin
        # gate against attacker-suppliable inputs is not an enforcement
        # gate at all -- refuse the decision outright and let the caller's
        # own local-enforcement fallback (the same one this repo's
        # enforcer.py already uses when it can tell in advance) run
        # instead. Found in review.
        if _requires_local_enforcement(policy):
            return jsonify({
                'error': 'this node\'s policy configures a gate that requires local '
                         'enforcement (margins / daily_envelope / no_self_dealing) -- '
                         'refusing to decide remotely',
                'node': 'dgx-spark',
            }), 409
        req = SpendRequest(**body['request'])
        state = AuthorityState(**body['state'])
        killed = bool(body.get('killed', False))
        skill = body.get('skill')
        context = body.get('context') or {}
        decision = decide(req, state, policy, skill=skill, context=context, killed=killed)
        return jsonify({
            'verdict': decision.verdict.value,
            'reason': decision.reason,
            'band': decision.band.value if decision.band else None,
            'node': 'dgx-spark',
        })
    except Exception as exc:
        return jsonify({'error': str(exc), 'node': 'dgx-spark'}), 400


if __name__ == '__main__':
    print('Custodian enforcement node — DGX Spark (primary)')
    app.run(host='0.0.0.0', port=8095, debug=False, threaded=True)
