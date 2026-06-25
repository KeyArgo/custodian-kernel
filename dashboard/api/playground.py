"""Interactive decision-engine playground.

Lets a visitor call the REAL custodian.policy.decide() function directly,
with a fresh, isolated AuthorityState that never touches the real
production state file -- so playing with this can never pollute the actual
audit log/pending-approval state shown elsewhere on the dashboard, and can
never trigger a real Stripe charge or a real Twilio SMS to the operator's
phone.

The /try-approve endpoint is the other half: it demonstrates, hands-on,
that there is no way to locally satisfy the approval check -- it always
rejects, because (unlike the real flow) there is no real Twilio Verify
service behind this sandboxed endpoint to check against. The real backend
is the same TwilioVerifyBackend used everywhere else in this system; this
endpoint exists only to make the "you can't just guess past it" property
something a visitor can feel, not just read.
"""
from __future__ import annotations

import sys
import time
from collections import defaultdict, deque
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `import custodian`

from custodian.policy import decide, load_policy
from custodian.types import AuthorityState, Band, SpendRequest

bp = Blueprint('playground', __name__)

# Simple in-memory, per-IP, per-process sliding-window rate limiter. No new
# dependency, no shared store -- appropriate for what this actually is (a
# demo endpoint with no auth, low expected traffic), not pretending to be a
# production-grade distributed limiter. Real limitation worth stating
# plainly: gunicorn runs multiple worker processes, each with its own copy
# of this dict, so the *effective* ceiling across the whole deployment is
# up to (limit x worker_count) for a client that gets round-robined across
# workers -- still strictly better than the zero rate limiting that existed
# before, not a claim of perfect enforcement.
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 30
_request_log: dict[str, deque] = defaultdict(deque)


def rate_limited(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        ip = request.headers.get('CF-Connecting-IP', request.remote_addr) or 'unknown'
        now = time.time()
        log = _request_log[ip]
        while log and now - log[0] > _RATE_LIMIT_WINDOW_SECONDS:
            log.popleft()
        if len(log) >= _RATE_LIMIT_MAX_REQUESTS:
            return jsonify({
                'error': f'Rate limit exceeded -- max {_RATE_LIMIT_MAX_REQUESTS} requests per '
                         f'{_RATE_LIMIT_WINDOW_SECONDS}s per IP on this demo endpoint.',
            }), 429
        log.append(now)
        return f(*args, **kwargs)
    return wrapper

POLICY_PATH = Path(__file__).resolve().parent / "playground_policy.yaml"

# A fresh, isolated state -- L2, $2.00 per-action cap, $10.00 session cap,
# nothing spent. Never read from or written to disk. Every visitor gets the
# same clean starting point, and nothing here ever touches the real
# production authority.json/audit_log.jsonl.
FRESH_STATE = AuthorityState(
    band=Band.L2, per_action_cap=250.00, session_cap=1000.00, spent_this_session=0.0,
)

# Loaded once at import time, not per-request. This file is a fixed demo
# policy that ships with the code -- it never changes at runtime, so
# re-reading and re-parsing it on every single /decide call (disk I/O + YAML
# parse + schema validation, every request) was pure waste, and combined
# with no rate limiting on a public endpoint, it made flooding cheaper to do
# damage with than it needed to be.
_PLAYGROUND_POLICY = load_policy(POLICY_PATH)


@bp.route('/decide', methods=['POST'])
@rate_limited
def try_decide():
    data = request.get_json(force=True, silent=True) or {}
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'amount must be a number'}), 400
    description = str(data.get('description', '') or 'untitled request')[:200]
    critical = bool(data.get('critical', False))
    kill_switch = bool(data.get('kill_switch', False))

    if amount <= 0:
        return jsonify({'error': 'amount must be positive'}), 400
    if amount > 1_000_000:
        return jsonify({'error': 'amount too large for this demo'}), 400

    request_obj = SpendRequest(amount=amount, description=description)
    context = {'critical': True} if critical else {}
    decision = decide(request_obj, FRESH_STATE, _PLAYGROUND_POLICY, context=context, killed=kill_switch)

    note = (
        'This is the real decide() function from custodian/policy/evaluator.py, '
        'called live against a fresh, isolated state. No real money moves and no '
        'real SMS is sent from this endpoint, regardless of the verdict.'
    )
    if kill_switch:
        note += (
            ' The kill switch override is the same custodian.policy.evaluator.decide(killed=True) '
            'check used by the real engine -- it runs first and overrides every other rule, '
            'with no band or amount that can route around it.'
        )

    return jsonify({
        'verdict': decision.verdict.value,
        'reason': decision.reason,
        'band': decision.band.value,
        'note': note,
    })


@bp.route('/try-approve', methods=['POST'])
@rate_limited
def try_approve():
    data = request.get_json(force=True, silent=True) or {}
    code = str(data.get('code', ''))[:32]

    # Deliberately always rejects. There is no real pending approval and no
    # real Twilio Verify check behind this sandboxed endpoint -- the point
    # is to make the structural property visceral: there is nothing local
    # to guess against, because the real check never happens on this
    # machine, it happens on Twilio's servers, against a code that only
    # ever exists there and on the operator's phone.
    return jsonify({
        'approved': False,
        'message': (
            f"Code '{code}' rejected. Not because it's wrong — there is no real "
            "approval pending here at all. In the real flow, the only thing that "
            "can confirm a code is the verification provider's own server, checked "
            "by approve.py. There is nothing on this machine for you, or the agent, "
            "to guess against."
        ),
    })
