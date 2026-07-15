"""Hermes Agent API endpoints - autonomous spend authority, live audit feed.

Sandbox state is read via `nemohermes exec` (custodian.adapters.nemoclaw),
never a host-side bind mount. A mount was used here previously; it went
through two failure modes — first staleness (lagged real writes by a sync
interval, misreported a real spend as unverified: see the history in
dashboard/scripts/agent_task_verified.py), then not existing on the
container at all (2026-07-14: this file was silently serving
DEFAULT_AUTHORITY fallback data and reporting connected:false on every
request, because the mount path had nothing behind it). exec is slower
per-call but is the only path that's actually correct.
"""
import json
import os
import time
from pathlib import Path

from flask import Blueprint, jsonify

from custodian.adapters.nemoclaw import NemoClawExecutor
from custodian.exceptions import NemoClawError

bp = Blueprint('hermes', __name__)

_cache = {}
_cache_ttl = 3  # seconds — fast enough to feel live, slow enough not to thrash disk

SANDBOX_NAME = os.environ.get('HERMES_SANDBOX_NAME', 'hermes-hackathon')
SKILL_STATE_DIR = '/sandbox/.hermes/skills/payments/stripe-spend/state'

_sandbox = NemoClawExecutor(
    sandbox_name=SANDBOX_NAME,
    fallback_binary_path='/home/argonaut/.local/bin/nemohermes',
)

OCSF_LOG_PATH = Path(os.getenv(
    'HERMES_OCSF_LOG_PATH',
    '/tmp/hermes-state-snapshot/ocsf_log.txt',
))

DEFAULT_AUTHORITY = {
    "band": "L2",
    "per_action_cap": 2.00,
    "session_cap": 10.00,
    "spent_this_session": 0.0,
}


def _cached(key, ttl=None):
    t = ttl or _cache_ttl
    now = time.time()
    if key in _cache:
        data, ts = _cache[key]
        if now - ts < t:
            return data, True
    return None, False


def _read_remote_file(filename):
    """Read a state file from inside the sandbox. Returns text or None
    (None covers both 'file doesn't exist yet' and 'sandbox unreachable' —
    existing callers already treat a None/empty result as 'nothing to show
    yet', which is the right degraded behavior for a health/summary read)."""
    try:
        return _sandbox.read_file(f'{SKILL_STATE_DIR}/{filename}')
    except NemoClawError as e:
        print(f"[hermes] Error reading {filename}: {e}")
        return None


def get_authority_state():
    cached, hit = _cached('authority')
    if hit:
        return cached

    raw = _read_remote_file('authority.json')
    state = json.loads(raw) if raw else dict(DEFAULT_AUTHORITY)
    state['connected'] = raw is not None

    # Split spend into autonomous (within the band, no human involved) vs
    # human-approved overrides — these can legitimately push the total past
    # session_cap, and conflating them makes the cap look broken on screen.
    # A refund nets back out of whichever bucket its ORIGINAL spend came
    # from (looked up by payment_intent_id), not just subtracted from the
    # total blindly -- otherwise an autonomous spend refunded later would
    # incorrectly shrink the override bucket instead, or vice versa.
    autonomous = 0.0
    approved_override = 0.0
    refunded_total = 0.0
    earned_total = 0.0
    spend_bucket_by_pi = {}
    raw_audit = _read_remote_file('audit_log.jsonl')
    if raw_audit:
        events = []
        for line in raw_audit.strip().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        for ev in events:
            if ev.get('event') == 'earned':
                earned_total += ev.get('amount', 0)
                continue
            if ev.get('event') != 'executed':
                continue
            pi_id = ev.get('payment_intent_id')
            amount = ev.get('amount', 0)
            bucket = 'override' if ev.get('approved_by') else 'autonomous'
            if pi_id:
                spend_bucket_by_pi[pi_id] = bucket
            if bucket == 'override':
                approved_override += amount
            else:
                autonomous += amount
        for ev in events:
            if ev.get('event') != 'refund_executed':
                continue
            amount = ev.get('amount', 0)
            refunded_total += amount
            bucket = spend_bucket_by_pi.get(ev.get('payment_intent_id'), 'autonomous')
            if bucket == 'override':
                approved_override -= amount
            else:
                autonomous -= amount
    state['autonomous_spent'] = round(autonomous, 2)
    state['approved_override_spent'] = round(approved_override, 2)
    state['refunded_total'] = round(refunded_total, 2)
    state['earned_total'] = round(earned_total, 2)
    # Net P&L: real revenue in, minus real spend net of refunds. Earning has
    # no band/cap (see earn.py) so it isn't part of the autonomous/override
    # split above -- it's a separate number entirely, not folded into spend.
    state['net_pnl'] = round(earned_total - (autonomous + approved_override), 2)

    # The autonomous budget still available this session WITHOUT any human
    # approval: session_cap minus what's been spent autonomously so far. This
    # is the same number the enforcement engine writes into an over-budget
    # escalation reason ("...exceeds remaining session budget $X") -- expose it
    # explicitly so the model cites a real, verifiable figure instead of
    # answering a "how much is left?" question with the amount already spent.
    session_cap = state.get('session_cap', 0) or 0
    # Use spent_this_session from authority.json (includes both autonomous and
    # approved-override spends) to match what the enforcement engine checks.
    # autonomous-only subtraction produced a misleading figure after override spends.
    total_spent = state.get('spent_this_session', autonomous + approved_override)
    state['autonomous_remaining'] = round(max(session_cap - total_spent, 0.0), 2)

    _cache['authority'] = (state, time.time())
    return state


def get_audit_log(limit=50):
    cached, hit = _cached(f'audit_{limit}')
    if hit:
        return cached

    raw = _read_remote_file('audit_log.jsonl')
    events = []
    if raw:
        for line in raw.strip().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Merge reasoning trace events written by the dashboard's operator endpoints.
    # These live in a companion file so they never collide with sandbox writes.
    reasoning_raw = _read_remote_file('reasoning_log.jsonl')
    if reasoning_raw:
        for line in reasoning_raw.strip().splitlines():
            try:
                ev = json.loads(line)
                if ev.get('event') == 'reasoning':
                    events.append(ev)
            except json.JSONDecodeError:
                continue

    events.sort(key=lambda e: e.get('ts', 0))
    events = events[-limit:][::-1]  # most recent first
    _cache[f'audit_{limit}'] = (events, time.time())
    return events


def get_policy_log(limit=20):
    """Raw kernel-level OCSF policy decisions (ALLOWED/DENIED), read from a
    plain text file maintained by a separate, narrowly-scoped dump script
    (dashboard/scripts/dump_ocsf_log.py) -- this process never touches the
    Docker socket itself. See that script's docstring for why that split
    matters on a shared production host."""
    cached, hit = _cached(f'policy_{limit}')
    if hit:
        return cached

    lines = []
    try:
        if OCSF_LOG_PATH.exists():
            raw = OCSF_LOG_PATH.read_text()
            ocsf_lines = [l for l in raw.splitlines() if l.strip()]
            lines = ocsf_lines[-limit:][::-1]
    except Exception as e:
        print(f"[hermes] Error reading policy log: {e}")

    _cache[f'policy_{limit}'] = (lines, time.time())
    return lines


def get_pending_approvals():
    """Returns at most one pending escalation, keyed synthetically — the real
    approval code lives only on Twilio's servers and the operator's phone,
    never in this file or anywhere the agent (or this dashboard) can read it."""
    cached, hit = _cached('pending')
    if hit:
        return cached

    raw = _read_remote_file('pending_approval.json')
    active = {}
    if raw:
        rec = json.loads(raw)
        if time.time() - rec.get('created_at', 0) < 600:
            active = {'pending': rec}
    _cache['pending'] = (active, time.time())
    return active


@bp.route('/status', methods=['GET'])
def status():
    return jsonify(get_authority_state())


@bp.route('/audit', methods=['GET'])
def audit():
    return jsonify(get_audit_log())


@bp.route('/pending', methods=['GET'])
def pending():
    return jsonify(get_pending_approvals())


@bp.route('/policy-log', methods=['GET'])
def policy_log():
    return jsonify(get_policy_log())


@bp.route('/summary', methods=['GET'])
def summary():
    """Single combined payload — what the dashboard polls."""
    return jsonify({
        'authority': get_authority_state(),
        'audit': get_audit_log(limit=25),
        'pending_approvals': get_pending_approvals(),
        'policy_log': get_policy_log(),
    })
