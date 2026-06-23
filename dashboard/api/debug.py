"""Client-side error capture — lets a developer (or an AI assistant troubleshooting
this dashboard remotely) see real browser-side JS errors without needing direct
access to anyone's browser console.

This is debug-only plumbing for building/operating the demo, not a feature shown
to judges. No auth on purpose (no secrets ever flow through it, just JS stack
traces from a public dashboard) — keep it that way; don't route real state through
this file.
"""
import json
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint('debug', __name__)

LOG_PATH = Path('/tmp/dashboard-client-errors.jsonl')
MAX_ENTRIES = 500


@bp.route('/report-error', methods=['POST'])
def report_error():
    data = request.get_json(force=True, silent=True) or {}
    entry = {
        'ts': time.time(),
        'iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'message': str(data.get('message', ''))[:2000],
        'stack': str(data.get('stack', ''))[:4000],
        'url': str(data.get('url', ''))[:500],
        'line': data.get('line'),
        'col': data.get('col'),
        'context': str(data.get('context', ''))[:200],
        'user_agent': request.headers.get('User-Agent', '')[:300],
    }

    lines = []
    if LOG_PATH.exists():
        lines = LOG_PATH.read_text().strip().splitlines()
    lines.append(json.dumps(entry))
    lines = lines[-MAX_ENTRIES:]
    LOG_PATH.write_text('\n'.join(lines) + '\n')

    return jsonify({'ok': True})


@bp.route('/errors', methods=['GET'])
def get_errors():
    limit = request.args.get('limit', 50, type=int)
    if not LOG_PATH.exists():
        return jsonify({'errors': []})
    lines = LOG_PATH.read_text().strip().splitlines()
    entries = [json.loads(l) for l in lines[-limit:][::-1] if l.strip()]
    return jsonify({'errors': entries, 'total_logged': len(lines)})


@bp.route('/errors', methods=['DELETE'])
def clear_errors():
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    return jsonify({'ok': True})
