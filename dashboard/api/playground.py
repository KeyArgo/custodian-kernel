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
from pathlib import Path

from flask import Blueprint, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, for `import custodian`

from custodian.policy import decide, load_policy
from custodian.types import AuthorityState, Band, SpendRequest

bp = Blueprint('playground', __name__)

POLICY_PATH = Path(__file__).resolve().parent / "playground_policy.yaml"

# A fresh, isolated state -- L2, $2.00 per-action cap, $10.00 session cap,
# nothing spent. Never read from or written to disk. Every visitor gets the
# same clean starting point, and nothing here ever touches the real
# production authority.json/audit_log.jsonl.
FRESH_STATE = AuthorityState(
    band=Band.L2, per_action_cap=2.00, session_cap=10.00, spent_this_session=0.0,
)


@bp.route('/decide', methods=['POST'])
def try_decide():
    data = request.get_json(force=True, silent=True) or {}
    try:
        amount = float(data.get('amount', 0))
    except (TypeError, ValueError):
        return jsonify({'error': 'amount must be a number'}), 400
    description = str(data.get('description', '') or 'untitled request')[:200]
    critical = bool(data.get('critical', False))

    if amount <= 0:
        return jsonify({'error': 'amount must be positive'}), 400
    if amount > 1_000_000:
        return jsonify({'error': 'amount too large for this demo'}), 400

    policy = load_policy(POLICY_PATH)
    request_obj = SpendRequest(amount=amount, description=description)
    context = {'critical': True} if critical else {}
    decision = decide(request_obj, FRESH_STATE, policy, context=context)

    return jsonify({
        'verdict': decision.verdict.value,
        'reason': decision.reason,
        'band': decision.band.value,
        'note': (
            'This is the real decide() function from custodian/policy/evaluator.py, '
            'called live against a fresh, isolated state. No real money moves and no '
            'real SMS is sent from this endpoint, regardless of the verdict.'
        ),
    })


@bp.route('/try-approve', methods=['POST'])
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
            "can confirm a code is Twilio's own server (verify.twilio.com), checked "
            "by approve.py. There is nothing on this machine for you, or the agent, "
            "to guess against."
        ),
    })
