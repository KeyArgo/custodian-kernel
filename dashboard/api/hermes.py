"""Hermes Agent API endpoints - autonomous spend authority, live audit feed.

argobox-command-center runs on the same host (argobox-lite) as the NemoClaw
sandbox, so this reads the mounted sandbox state directly off disk — no SSH,
no extra network hop, one less thing that can fail during a demo.
"""
import json
import os
import time
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint('hermes', __name__)

_cache = {}
_cache_ttl = 3  # seconds — fast enough to feel live, slow enough not to thrash disk

SKILL_PATH = Path(os.getenv(
    'HERMES_SKILL_STATE_PATH',
    '/tmp/hermes-mount/sandbox/.hermes/skills/payments/stripe-spend/state',
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
    """Read a state file out of the sandbox's mounted state dir. Returns text or None."""
    path = SKILL_PATH / filename
    try:
        if path.exists():
            return path.read_text()
    except Exception as e:
        print(f"[hermes] Error reading {path}: {e}")
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
    autonomous = 0.0
    approved_override = 0.0
    raw_audit = _read_remote_file('audit_log.jsonl')
    if raw_audit:
        for line in raw_audit.strip().splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get('event') != 'executed':
                continue
            if ev.get('approved_by'):
                approved_override += ev.get('amount', 0)
            else:
                autonomous += ev.get('amount', 0)
    state['autonomous_spent'] = round(autonomous, 2)
    state['approved_override_spent'] = round(approved_override, 2)

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
    events = events[-limit:][::-1]  # most recent first
    _cache[f'audit_{limit}'] = (events, time.time())
    return events


def get_policy_log(limit=20):
    """Raw kernel-level OCSF policy decisions (ALLOWED/DENIED) from the sandbox
    container's own docker logs — the actual proof of kernel-level enforcement,
    not application-level reasoning."""
    cached, hit = _cached(f'policy_{limit}')
    if hit:
        return cached

    lines = []
    try:
        import docker
        client = docker.from_env()
        sandbox = next(
            (c for c in client.containers.list()
             if c.name.startswith('openshell-hermes-hackathon')),
            None,
        )
        if sandbox:
            raw = sandbox.logs(tail=300).decode('utf-8', errors='replace')
            ocsf_lines = [l for l in raw.splitlines() if 'OCSF' in l]
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
