"""Operator-only control panel for running the real demo arc live.

This is NOT exposed on the public dashboard or the public Pages frontend --
it's a same-origin page served directly by this Flask app at /operator,
used only by the project owner while presenting, so they can click buttons
instead of typing commands at a terminal during a live demo.

Every action here shells out to the SAME real scripts demo_moment.sh uses
(spend.py/refund.py/approve.py/kill_toggle.py) against the real NemoClaw
sandbox via `nemohermes <sandbox> exec`. Nothing here is simulated: this
panel moves real Stripe test-mode money and triggers real Twilio SMS sends,
which is exactly why it requires a real password, unlike every other public
endpoint in this app.

A deliberate decision tied to this hackathon's own design claim: hackathon
judges/visitors do NOT get this panel. Letting an anonymous stranger
self-approve via a code sent to the same device they're already holding
would stop being an out-of-band human approval and just become a form with
two fields -- weakening the exact security property this project exists to
demonstrate. Visitors get the playground (real decide() engine, simulated
state) instead. Only the operator gets the real arc, and only with this
password.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
import time
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint('operator', __name__)

SECRET_FILE = Path(__file__).resolve().parent.parent / 'secrets' / 'operator.env'
SANDBOX_NAME = os.environ.get('HERMES_SANDBOX_NAME', 'hermes-hackathon')
SCRIPTS_DIR = '/sandbox/.hermes/skills/payments/stripe-spend/scripts'
TOKEN_TTL_SECONDS = 4 * 3600  # one demo session's worth, re-enter password after


def _secret(name):
    if not SECRET_FILE.exists():
        raise RuntimeError(f'{SECRET_FILE} not found -- create it with {name}=... (chmod 600)')
    for line in SECRET_FILE.read_text().splitlines():
        if line.startswith(f'{name}='):
            return line.split('=', 1)[1].strip()
    raise RuntimeError(f'{name} not found in {SECRET_FILE}')


def _sign(payload: str) -> str:
    key = _secret('OPERATOR_PANEL_SECRET').encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def _make_token() -> str:
    expires = str(int(time.time()) + TOKEN_TTL_SECONDS)
    return f'{expires}.{_sign(expires)}'


def _token_valid(token: str) -> bool:
    if not token or '.' not in token:
        return False
    expires, sig = token.rsplit('.', 1)
    if not expires.isdigit():
        return False
    if int(expires) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(expires))


def require_operator(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('X-Operator-Token', '')
        if not _token_valid(token):
            return jsonify({'error': 'not authenticated'}), 401
        return f(*args, **kwargs)
    return wrapper


def _run_script(script: str, *script_args: str, timeout: int = 30):
    cmd = ['nemohermes', SANDBOX_NAME, 'exec', '--', 'python3',
           f'{SCRIPTS_DIR}/{script}', *script_args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            'returncode': proc.returncode,
            'stdout': proc.stdout.strip(),
            'stderr': proc.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {'returncode': -1, 'stdout': '', 'stderr': f'timed out after {timeout}s'}


@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    password = str(data.get('password', ''))
    real_password = _secret('OPERATOR_PANEL_PASSWORD')
    if not hmac.compare_digest(password, real_password):
        return jsonify({'error': 'wrong password'}), 401
    return jsonify({'token': _make_token(), 'expires_in': TOKEN_TTL_SECONDS})


@bp.route('/earn', methods=['POST'])
@require_operator
def earn():
    data = request.get_json(force=True, silent=True) or {}
    amount = str(data.get('amount', ''))
    description = str(data.get('description', ''))[:200]
    result = _run_script('earn.py', '--amount', amount, '--description', description)
    return jsonify(result)


@bp.route('/spend', methods=['POST'])
@require_operator
def spend():
    data = request.get_json(force=True, silent=True) or {}
    amount = str(data.get('amount', ''))
    description = str(data.get('description', ''))[:200]
    result = _run_script('spend.py', '--amount', amount, '--description', description)
    return jsonify(result)


@bp.route('/refund', methods=['POST'])
@require_operator
def refund():
    data = request.get_json(force=True, silent=True) or {}
    pi_id = str(data.get('payment_intent_id', ''))
    amount = str(data.get('amount', ''))
    description = str(data.get('description', ''))[:200]
    result = _run_script('refund.py', '--payment-intent-id', pi_id,
                          '--amount', amount, '--description', description)
    return jsonify(result)


@bp.route('/approve', methods=['POST'])
@require_operator
def approve():
    data = request.get_json(force=True, silent=True) or {}
    code = str(data.get('code', ''))[:32]
    approved_by = str(data.get('approved_by', 'Operator'))[:100]
    result = _run_script('approve.py', code, '--approved-by', approved_by)
    return jsonify(result)


@bp.route('/kill', methods=['POST'])
@require_operator
def kill():
    data = request.get_json(force=True, silent=True) or {}
    by = str(data.get('by', 'Operator'))[:100]
    reason = str(data.get('reason', ''))[:200]
    args = ['--by', by]
    if reason:
        args += ['--reason', reason]
    result = _run_script('kill_toggle.py', 'engage', *args)
    return jsonify(result)


@bp.route('/resume', methods=['POST'])
@require_operator
def resume():
    data = request.get_json(force=True, silent=True) or {}
    by = str(data.get('by', 'Operator'))[:100]
    result = _run_script('kill_toggle.py', 'release', '--by', by)
    return jsonify(result)


import json as _json
_PENDING_CODE_PATH = Path('/tmp/hermes-mount/sandbox/.hermes/skills/payments/stripe-spend/state/pending_code.json')


@bp.route('/pending_code', methods=['GET'])
@require_operator
def pending_code():
    if not _PENDING_CODE_PATH.exists():
        return jsonify({'code': None, 'reason': 'no pending code'})
    try:
        data = _json.loads(_PENDING_CODE_PATH.read_text())
    except (ValueError, OSError):
        return jsonify({'code': None, 'reason': 'unreadable'})
    if time.time() > data.get('expires_at', 0):
        return jsonify({'code': None, 'reason': 'expired'})
    return jsonify({'code': data.get('code'), 'expires_at': data.get('expires_at')})
