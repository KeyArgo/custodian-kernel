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
import logging
import math
import os
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


_log = logging.getLogger(__name__)


def require_operator(f):
    """Verify the X-Operator-Token header against the signed token from /login."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.headers.get('X-Operator-Token', '')
        try:
            if not _token_valid(token):
                return jsonify({'error': 'unauthorized'}), 401
        except Exception:
            # Fail safe (deny) either way, but a bug inside _token_valid
            # itself (e.g. a corrupted secrets file) used to look identical
            # to "wrong token" in the logs -- silently hiding a real error
            # from whoever is debugging a login problem.
            _log.exception('require_operator: _token_valid raised')
            return jsonify({'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return wrapper


from custodian.adapters.nemoclaw import NemoClawExecutor
from custodian.exceptions import SandboxGatewayDownError, SandboxTimeoutError

_sandbox = NemoClawExecutor(
    sandbox_name=SANDBOX_NAME,
    # nemohermes may not be on the PATH when Flask starts from a venv;
    # fall back to the known install location.
    fallback_binary_path='/home/argonaut/.local/bin/nemohermes',
)


def _run_script(script: str, *script_args: str, timeout: int = 30):
    """Kept as a thin dict-returning shim so every existing call site
    (earn/spend/refund/approve/kill/resume) is unchanged -- only the
    implementation moved to the reusable NemoClawExecutor adapter
    (custodian/adapters/nemoclaw.py). Infrastructure failures (gateway
    down / timeout) are converted back to the same dict shape a genuine
    script failure would have produced, so callers and the frontend don't
    need to distinguish -- but the raised exception types are still there
    for anything (e.g. /sandbox/status below) that wants to tell them apart."""
    try:
        result = _sandbox.run(f'{SCRIPTS_DIR}/{script}', *script_args, timeout=timeout)
        return result.to_dict()
    except SandboxTimeoutError:
        return {'returncode': -1, 'stdout': '', 'stderr': f'timed out after {timeout}s'}
    except SandboxGatewayDownError as e:
        return {'returncode': -1, 'stdout': '', 'stderr': str(e)}


@bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True, silent=True) or {}
    password = str(data.get('password', ''))
    try:
        real_password = _secret('OPERATOR_PANEL_PASSWORD')
    except RuntimeError:
        # Operator panel not configured on this host (secrets/operator.env
        # missing). Return clean JSON the frontend can parse, not a raw HTML
        # 500 that breaks its r.json().
        return jsonify({'error': 'operator panel is not configured on this server'}), 503
    if not hmac.compare_digest(password, real_password):
        return jsonify({'error': 'wrong password'}), 401
    return jsonify({'token': _make_token(), 'expires_in': TOKEN_TTL_SECONDS})


_DEMO_AMOUNT_MAX = 10_000.00  # test-mode Stripe limit for demo; prevents junk PI pollution

@bp.route('/earn', methods=['POST'])
@require_operator
def earn():
    data = request.get_json(force=True, silent=True) or {}
    try:
        amount = float(data.get('amount', 0))
        if not math.isfinite(amount) or amount <= 0 or amount > _DEMO_AMOUNT_MAX:
            return jsonify({'error': f'amount must be between 0 and {_DEMO_AMOUNT_MAX}'}), 400
    except (TypeError, ValueError):
        return jsonify({'error': 'amount must be a number'}), 400
    description = str(data.get('description', ''))[:200]
    result = _run_script('earn.py', '--amount', str(amount), '--description', description)
    _write_reasoning('earn.py', result)
    return jsonify(result)


def _read_flask_kill_switch() -> tuple:
    """Read the Flask-layer kill switch written by /kill and /resume.
    Returns (killed: bool, by: str, reason: str). Fails open to False if absent."""
    ks_path = Path.home() / '.custodian' / 'kill_switch.json'
    if not ks_path.exists():
        return False, '', ''
    try:
        d = json.loads(ks_path.read_text())
        return bool(d.get('killed', False)), d.get('by', ''), d.get('reason', '')
    except Exception:
        return False, '', ''


def _write_flask_kill_switch(killed: bool, by: str, reason: str = '') -> None:
    """Write the Flask-layer kill switch state for the pre-check in /spend."""
    ks_path = Path.home() / '.custodian' / 'kill_switch.json'
    ks_path.parent.mkdir(parents=True, exist_ok=True)
    ks_path.write_text(json.dumps({'killed': killed, 'by': by, 'reason': reason}))


@bp.route('/spend', methods=['POST'])
@require_operator
def spend():
    data = request.get_json(force=True, silent=True) or {}
    try:
        amount = float(data.get('amount', 0))
        if not math.isfinite(amount) or amount <= 0 or amount > _DEMO_AMOUNT_MAX:
            return jsonify({'error': f'amount must be between 0 and {_DEMO_AMOUNT_MAX}'}), 400
    except (TypeError, ValueError):
        return jsonify({'error': 'amount must be a number'}), 400
    description = str(data.get('description', ''))[:200]

    # Step 1 ("autonomous spend, no human needed") is the demo's first spend
    # action and runs before the kill-switch arc (Steps 4-6) even starts. The
    # kill switch is shared global state across every visitor, so a prior
    # visitor's Step 4/5 run (or an abandoned one that never reached Step 6)
    # can leave it engaged and permanently block Step 1 for everyone after
    # them. auto_release_kill_switch lets the frontend say "this call is
    # upstream of the kill-switch demo -- clear any stale engagement before
    # evaluating" so the demo self-heals instead of staying stuck. Only the
    # Step 1 button sends this flag; Step 5 ("prove kill switch blocks
    # everything") must never send it, or it would erase the exact denial
    # it's there to demonstrate.
    if data.get('auto_release_kill_switch'):
        killed, _, _ = _read_flask_kill_switch()
        if killed:
            auto_by = 'auto-recovery (stale kill switch cleared by Step 1)'
            release_result = _run_script('kill_toggle.py', 'release', '--by', auto_by)
            _write_flask_kill_switch(killed=False, by=auto_by)
            _write_reasoning('kill_toggle.py', release_result)

    # Flask-layer kill switch pre-check: enforce before calling nemohermes.
    # This guards against ephemeral sandbox exec contexts where the sandbox DB
    # written by kill_toggle.py may not persist into spend.py's exec.
    killed, kill_by, kill_reason = _read_flask_kill_switch()
    if killed:
        reason_str = f', reason: {kill_reason}' if kill_reason else ''
        denied_line = (f'[authority] DENIED — kill switch is engaged (by {kill_by or "operator"}'
                       f'{reason_str}).')
        note_line = ('[authority] This overrides every band and cap, with no exceptions. '
                     'Run `custodian resume --by <name>` to release it.')
        return jsonify({
            'returncode': 3,
            'stdout': f'{denied_line}\n{note_line}',
            'stderr': '',
        })

    result = _run_script('spend.py', '--amount', str(amount), '--description', description)
    _write_reasoning('spend.py', result)
    return jsonify(result)


@bp.route('/refund', methods=['POST'])
@require_operator
def refund():
    data = request.get_json(force=True, silent=True) or {}
    pi_id = str(data.get('payment_intent_id', ''))
    try:
        amount = float(data.get('amount', 0))
        if not math.isfinite(amount) or amount <= 0 or amount > _DEMO_AMOUNT_MAX:
            return jsonify({'error': f'amount must be between 0 and {_DEMO_AMOUNT_MAX}'}), 400
    except (TypeError, ValueError):
        return jsonify({'error': 'amount must be a number'}), 400
    description = str(data.get('description', 'refund'))[:200]

    # refund.py always escalates (self-dealing) and sends the Twilio SMS itself.
    # The only thing worth catching here is an explicit kill-switch denial — for
    # that case we let the script run and it will print the denial and exit 3.
    # Previously this block returned 402 early for ANY non-autonomous verdict,
    # which prevented refund.py from running and meant no SMS was ever sent.
    result = _run_script('refund.py', '--payment-intent-id', pi_id,
                          '--amount', str(amount), '--description', description)
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
    # Write Flask-layer kill switch so /spend can enforce it even if the sandbox
    # exec context is ephemeral and doesn't share the sandbox SQLite state.
    _write_flask_kill_switch(killed=True, by=by, reason=reason)
    _write_reasoning('kill_toggle.py', result)
    return jsonify(result)


@bp.route('/resume', methods=['POST'])
@require_operator
def resume():
    data = request.get_json(force=True, silent=True) or {}
    by = str(data.get('by', 'Operator'))[:100]
    result = _run_script('kill_toggle.py', 'release', '--by', by)
    # Clear Flask-layer kill switch so /spend proceeds normally after release.
    _write_flask_kill_switch(killed=False, by=by)
    _write_reasoning('kill_toggle.py', result)
    return jsonify(result)


import json
import os

SKILL_STATE_DIR = '/sandbox/.hermes/skills/payments/stripe-spend/state'

# Escalation metadata (amount/description/reason) — written by
# notify.write_pending(). Never has a code field.
_PENDING_APPROVAL_PATH = f'{SKILL_STATE_DIR}/pending_approval.json'
# The real, server-generated 6-digit code — written by notify.py's
# send_approval_code() (deliberately server-known, so the operator panel can
# display/auto-fill it on screen; see notify.py's module docstring). A
# SEPARATE file from pending_approval.json above.
_PENDING_CODE_PATH = f'{SKILL_STATE_DIR}/pending_code.json'


@bp.route('/pending_code', methods=['GET'])
@require_operator
def pending_code():
    """Previously this read both paths through a host-side bind mount that
    doesn't exist on this container (2026-07-14 finding), so it always fell
    through to 'no pending code' regardless of what was actually pending —
    and separately, the two path variables were named backwards from what
    they pointed to, so even a working mount would have gated the whole
    response on the wrong file's existence. Both fixed here: read via
    nemohermes exec (custodian.adapters.nemoclaw), and the code file is now
    treated as the primary source of truth for `pending`, not a fallback."""
    try:
        meta_raw = _sandbox.read_file(_PENDING_APPROVAL_PATH)
        code_raw = _sandbox.read_file(_PENDING_CODE_PATH)
    except (SandboxGatewayDownError, SandboxTimeoutError) as e:
        return jsonify({'pending': False, 'code': None, 'reason': str(e)})

    meta = {}
    if meta_raw:
        try:
            meta = json.loads(meta_raw)
        except ValueError:
            meta = {}

    code = None
    if code_raw:
        try:
            code_data = json.loads(code_raw)
            if time.time() <= code_data.get('expires_at', 0):
                code = code_data.get('code')
        except ValueError:
            pass

    if code is None and not meta:
        return jsonify({'pending': False, 'code': None, 'reason': 'no pending code'})

    # Return the escalation metadata and the code so the UI can auto-fill it.
    return jsonify({
        'pending': True,
        'code': code,
        'amount': meta.get('amount'),
        'description': meta.get('description'),
        'kind': meta.get('kind', 'spend'),
        'created_at': meta.get('created_at'),
    })


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


def _client_ip() -> str:
    """X-Forwarded-For is client-supplied input -- trusting it
    unconditionally lets a client rotate the header value per request to
    get a fresh SMS rate-limit bucket every time (each real forward costs
    real money via Twilio). Only honored when the operator has explicitly
    confirmed, via TRUSTED_PROXY_HEADER=X-Forwarded-For, that a trusted
    proxy terminates every path to this process and overwrites any
    client-supplied header of the same name; otherwise falls back to
    request.remote_addr, which the client cannot forge. Same fix applied
    to nemotron_chat.py/playground.py/stripe_webhook.py this session."""
    if os.environ.get('TRUSTED_PROXY_HEADER') == 'X-Forwarded-For':
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


@bp.route('/forward_code', methods=['POST'])
@require_operator
def forward_code():
    """Forward the pending SMS code to a visitor-supplied phone number via Twilio."""
    import urllib.request, urllib.parse, base64
    ip = _client_ip()
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
            result = json.loads(resp.read())
        return jsonify({'ok': True, 'sid': result.get('sid'), 'to': phone})
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        try:
            detail = json.loads(body)
            msg = detail.get('message', body)
        except Exception:
            msg = body[:200]
        try:
            twilio_code = json.loads(body).get('code') if body.startswith('{') else None
        except Exception:
            twilio_code = None
        return jsonify({'ok': False, 'error': msg, 'twilio_code': twilio_code, 'to': phone}), 502
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e), 'to': phone}), 502


_AUDIT_LOG_PATH = f'{SKILL_STATE_DIR}/audit_log.jsonl'
_AUTHORITY_PATH = f'{SKILL_STATE_DIR}/authority.json'
_REASONING_LOG_PATH = f'{SKILL_STATE_DIR}/reasoning_log.jsonl'


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
        'iso': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }
    try:
        _sandbox.write_file(_REASONING_LOG_PATH, json.dumps(event) + '\n', append=True)
    except Exception:
        pass


@bp.route('/reset', methods=['POST'])
def reset_demo():
    """Reset the demo: archives audit log, zeroes session spend, clears pending code.

    Auth accepts EITHER a valid operator token (from /login) OR the
    OPERATOR_PANEL_PASSWORD. The token path is what makes the demo durable —
    it lets the panel offer one-click "reset & retry" without re-prompting for
    the password every time the session budget runs out between runs, which is
    the exact silent breakage this endpoint exists to undo."""
    data = request.get_json(force=True, silent=True) or {}
    token = request.headers.get('X-Operator-Token', '')
    authed = False
    try:
        authed = _token_valid(token)
    except Exception:
        authed = False
    if not authed:
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
        if _sandbox.read_file(_AUDIT_LOG_PATH) is not None:
            ts = int(time.time())
            archive = f'{_AUDIT_LOG_PATH}.reset-{ts}'
            _sandbox.move_file(_AUDIT_LOG_PATH, archive)
            steps.append(f'audit_log archived → {archive.rsplit("/", 1)[-1]}')
        else:
            steps.append('audit_log not found — skipped')

        # Zero session spend in authority.json, preserve band and caps
        auth_raw = _sandbox.read_file(_AUTHORITY_PATH)
        if auth_raw is not None:
            auth = json.loads(auth_raw)
            auth['spent_this_session'] = 0.0
            _sandbox.write_file(_AUTHORITY_PATH, json.dumps(auth, indent=2))
            steps.append(f'session spend zeroed (band={auth.get("band")}, cap=${auth.get("per_action_cap")})')
        else:
            steps.append('authority.json not found — skipped')

        # Clear any pending escalation code
        if _sandbox.read_file(_PENDING_CODE_PATH) is not None:
            _sandbox.delete_file(_PENDING_CODE_PATH)
            steps.append('pending_code cleared')

        # Clear Flask-layer kill switch so post-reset spends aren't silently denied
        _write_flask_kill_switch(killed=False, by='reset')
        steps.append('flask kill switch cleared')

        return jsonify({'ok': True, 'steps': steps})
    except Exception as e:
        return jsonify({'error': str(e), 'steps': steps}), 500


# ── Spark enforcement node management ─────────────────────────────────────────

@bp.route('/spark/status', methods=['GET'])
@require_operator
def spark_status():
    try:
        from custodian.policy.enforcer import spark_health
        return jsonify(spark_health())
    except ImportError:
        return jsonify({'enabled': False, 'reachable': False, 'reason': 'local-only mode'})


@bp.route('/spark/disable', methods=['POST'])
@require_operator
def spark_disable_route():
    try:
        from custodian.policy.enforcer import spark_disable, spark_health
        spark_disable()
        return jsonify({'ok': True, 'action': 'disabled', 'status': spark_health()})
    except ImportError:
        return jsonify({'ok': False, 'error': 'enforcer not loaded'})


@bp.route('/spark/enable', methods=['POST'])
@require_operator
def spark_enable_route():
    try:
        from custodian.policy.enforcer import spark_enable, spark_health
        spark_enable()
        return jsonify({'ok': True, 'action': 'enabled', 'status': spark_health()})
    except ImportError:
        return jsonify({'ok': False, 'error': 'enforcer not loaded'})


# ── NemoClaw sandbox health ─────────────────────────────────────────────────

@bp.route('/sandbox/status', methods=['GET'])
@require_operator
def sandbox_status():
    """Health of the NemoClaw sandbox that /earn, /spend, /refund, /approve,
    and /kill all execute inside. Distinct from /spark/status -- Spark is the
    enforcement *decision* layer, this is the script *execution* layer; a
    sandbox gateway outage looks identical to a Spark outage from the
    frontend's error text unless you check this route."""
    try:
        health = _sandbox.doctor()
        return jsonify({
            'ok': health.ok,
            'sandbox': health.sandbox,
            'status': health.status,
            'failed': health.failed,
            'warnings': health.warnings,
            'checks': [c.__dict__ for c in health.checks],
        })
    except (SandboxGatewayDownError, SandboxTimeoutError) as e:
        return jsonify({'ok': False, 'error': str(e)}), 503
