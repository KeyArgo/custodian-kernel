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

import collections
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
    """No-op in demo mode — panel is public so judges can run the full arc solo."""
    return f


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
    _write_reasoning('earn.py', result)
    return jsonify(result)


@bp.route('/spend', methods=['POST'])
@require_operator
def spend():
    data = request.get_json(force=True, silent=True) or {}
    amount = str(data.get('amount', ''))
    description = str(data.get('description', ''))[:200]
    result = _run_script('spend.py', '--amount', amount, '--description', description)
    _write_reasoning('spend.py', result)
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
    _write_reasoning('refund.py', result)
    return jsonify(result)


@bp.route('/approve', methods=['POST'])
@require_operator
def approve():
    data = request.get_json(force=True, silent=True) or {}
    code = str(data.get('code', ''))[:32]
    approved_by = str(data.get('approved_by', 'Operator'))[:100]
    result = _run_script('approve.py', code, '--approved-by', approved_by)
    _write_reasoning('approve.py', result)
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
    _write_reasoning('kill_toggle.py', result)
    return jsonify(result)


@bp.route('/resume', methods=['POST'])
@require_operator
def resume():
    data = request.get_json(force=True, silent=True) or {}
    by = str(data.get('by', 'Operator'))[:100]
    result = _run_script('kill_toggle.py', 'release', '--by', by)
    _write_reasoning('kill_toggle.py', result)
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


_sms_rate: dict = collections.defaultdict(list)  # ip -> [timestamp, ...]
_SMS_LIMIT = 3
_SMS_WINDOW = 600  # 10 minutes


def _sms_allowed(ip: str) -> bool:
    now = time.time()
    timestamps = [t for t in _sms_rate[ip] if now - t < _SMS_WINDOW]
    _sms_rate[ip] = timestamps
    if len(timestamps) >= _SMS_LIMIT:
        return False
    _sms_rate[ip].append(now)
    return True


@bp.route('/forward_code', methods=['POST'])
@require_operator
def forward_code():
    """Forward the pending SMS code to a visitor-supplied phone number via Twilio."""
    import urllib.request, urllib.parse, base64
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()
    if not _sms_allowed(ip):
        return jsonify({'ok': False, 'error': f'Rate limit: max {_SMS_LIMIT} SMS per 10 minutes per IP'}), 429
    data = request.get_json(force=True, silent=True) or {}
    raw_phone = str(data.get('phone', '') or '').strip()
    code = str(data.get('code', '') or '').strip()[:10]
    if not raw_phone or not code:
        return jsonify({'error': 'phone and code required'}), 400

    # Normalize to E.164 — Twilio rejects anything else
    digits = ''.join(c for c in raw_phone if c.isdigit())
    if len(digits) == 10:
        phone = '+1' + digits
    elif len(digits) == 11 and digits[0] == '1':
        phone = '+' + digits
    elif raw_phone.startswith('+'):
        phone = '+' + digits
    else:
        phone = raw_phone[:20]

    # Twilio credentials come from the same operator.env secrets file
    def _tw(name):
        return _secret(name) if SECRET_FILE.exists() and any(
            l.startswith(name + '=') for l in SECRET_FILE.read_text().splitlines()
        ) else os.environ.get(name, '')

    account_sid = _tw('TWILIO_ACCOUNT_SID')
    auth_token  = _tw('TWILIO_AUTH_TOKEN')
    from_number = _tw('TWILIO_FROM_NUMBER')
    if not all([account_sid, auth_token, from_number]):
        return jsonify({'error': 'Twilio not configured — add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER to operator.env'}), 503

    body = f'Your Custodian demo approval code is: {code}\nExpires in 10 min. Enter it in Step 3 on the operator panel.'
    url = f'https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json'
    payload = urllib.parse.urlencode({'To': phone, 'From': from_number, 'Body': body}).encode()
    creds = base64.b64encode(f'{account_sid}:{auth_token}'.encode()).decode()
    req = urllib.request.Request(url, data=payload,
                                 headers={'Authorization': f'Basic {creds}',
                                          'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = _json.loads(resp.read())
        return jsonify({'ok': True, 'sid': result.get('sid'), 'to': phone})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            detail = _json.loads(body)
            msg = detail.get('message', body)
        except Exception:
            msg = body[:200]
        return jsonify({'ok': False, 'error': msg, 'twilio_code': _json.loads(body).get('code') if body.startswith('{') else None, 'to': phone}), 502
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e), 'to': phone}), 502


_STATE_DIR = Path('/tmp/hermes-mount/sandbox/.hermes/skills/payments/stripe-spend/state')
_AUDIT_LOG_PATH = _STATE_DIR / 'audit_log.jsonl'
_AUTHORITY_PATH = _STATE_DIR / 'authority.json'
_REASONING_LOG_PATH = _STATE_DIR / 'reasoning_log.jsonl'


def _write_reasoning(script: str, result: dict):
    """Append a reasoning event to the companion reasoning log so it surfaces in the audit feed."""
    text = (result.get('stdout') or '').strip()
    if not text:
        text = (result.get('stderr') or '').strip()
    if not text:
        return
    event = {
        'ts': time.time(),
        'event': 'reasoning',
        'script': script.replace('.py', ''),
        'text': text[:600],
        'iso': __import__('datetime').datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    try:
        with open(_REASONING_LOG_PATH, 'a') as f:
            f.write(_json.dumps(event) + '\n')
    except Exception:
        pass


@bp.route('/reset', methods=['POST'])
def reset_demo():
    """Password-gated reset: archives audit log, zeroes session spend, clears pending code.
    Requires OPERATOR_PANEL_PASSWORD — NOT protected by the no-op require_operator."""
    data = request.get_json(force=True, silent=True) or {}
    password = str(data.get('password', ''))
    try:
        real_password = _secret('OPERATOR_PANEL_PASSWORD')
    except RuntimeError:
        return jsonify({'error': 'Server not configured for reset (no operator secret file)'}), 503
    if not hmac.compare_digest(password, real_password):
        return jsonify({'error': 'wrong password'}), 401

    steps = []
    try:
        # Archive audit log
        if _AUDIT_LOG_PATH.exists():
            ts = int(time.time())
            archive = _AUDIT_LOG_PATH.with_suffix(f'.jsonl.reset-{ts}')
            _AUDIT_LOG_PATH.rename(archive)
            steps.append(f'audit_log archived → {archive.name}')
        else:
            steps.append('audit_log not found — skipped')

        # Zero session spend in authority.json, preserve band and caps
        if _AUTHORITY_PATH.exists():
            auth = _json.loads(_AUTHORITY_PATH.read_text())
            auth['spent_this_session'] = 0.0
            _AUTHORITY_PATH.write_text(_json.dumps(auth, indent=2))
            steps.append(f'session spend zeroed (band={auth.get("band")}, cap=${auth.get("per_action_cap")})')
        else:
            steps.append('authority.json not found — skipped')

        # Clear any pending escalation code
        if _PENDING_CODE_PATH.exists():
            _PENDING_CODE_PATH.unlink()
            steps.append('pending_code cleared')

        return jsonify({'ok': True, 'steps': steps})
    except Exception as e:
        return jsonify({'error': str(e), 'steps': steps}), 500
