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
from custodian.policy.schema import Policy
from custodian.types import AuthorityState, SpendRequest

app = Flask(__name__)

_POLICY_PATH = Path(__file__).parent / 'policy.yaml'

_policy: Policy | None = None


def _load_policy() -> Policy:
    global _policy
    if _policy is None:
        if _POLICY_PATH.exists():
            import yaml
            _policy = Policy.from_dict(yaml.safe_load(_POLICY_PATH.read_text()))
        else:
            _policy = Policy.default()
    return _policy


@app.get('/health')
def health():
    return jsonify({'ok': True, 'node': 'dgx-spark', 'role': 'enforcement-primary'})


@app.post('/decide')
def decide_endpoint():
    body = flask_request.get_json(force=True, silent=True) or {}
    try:
        req = SpendRequest(**body['request'])
        state = AuthorityState(**body['state'])
        policy = _load_policy()
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
