"""Client-side error capture — lets a developer (or an AI assistant troubleshooting
this dashboard remotely) see real browser-side JS errors without needing direct
access to anyone's browser console.

This is debug-only plumbing for building/operating the demo, not a feature shown
to judges. No auth on purpose (no secrets ever flow through it, just JS stack
traces from a public dashboard) — keep it that way; don't route real state through
this file.
"""
import json
import os
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

bp = Blueprint('debug', __name__)

LOG_PATH = Path('/tmp/dashboard-client-errors.jsonl')
MAX_ENTRIES = 500
# Generous but bounded: line/col are normally small integers, but nothing
# upstream constrains what the client sends. Uncapped, they were the one
# field in this route with no length limit at all -- five megabytes of
# 'A' in `line` (a single unauthenticated POST) grew the log file by 5MB,
# and every subsequent write does a full read-modify-rewrite of the whole
# file, so a handful of requests drove real, compounding disk cost. Found
# in review.
_MAX_LINE_COL_LEN = 20


def _safe_write_lines(path: Path, lines: list) -> None:
    """Write lines to `path`, refusing to follow a symlink there.

    `path` is a fixed, predictable location in world-writable /tmp, shared
    with every other process on this "public-facing... shared production
    host running many other real services" (this app's own words
    elsewhere). A plain read-then-rewrite via Path.write_text() follows a
    symlink transparently: any local user/process able to pre-create
    `path -> /some/victim/file` gets that file's content silently merged
    with attacker-controlled JSONL on the very next legitimate visitor's
    /report-error call -- and, since writes are capped to the last
    MAX_ENTRIES lines, eventually evicted and fully overwritten with
    attacker data (CWE-59, improper link resolution before file access).
    O_NOFOLLOW makes the open() itself fail (ELOOP) if the final path
    component is a symlink, instead of following it. Found in review.
    """
    data = ('\n'.join(lines) + '\n').encode('utf-8')
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)


def _safe_read_lines(path: Path) -> list:
    """Read `path`, refusing to follow a symlink there -- same rationale
    as _safe_write_lines (reading through an attacker-planted symlink can
    leak an arbitrary file's content into the /errors response)."""
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, 'r', encoding='utf-8') as f:
        return f.read().strip().splitlines()


@bp.route('/report-error', methods=['POST'])
def report_error():
    data = request.get_json(force=True, silent=True) or {}
    entry = {
        'ts': time.time(),
        'iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'message': str(data.get('message', ''))[:2000],
        'stack': str(data.get('stack', ''))[:4000],
        'url': str(data.get('url', ''))[:500],
        'line': str(data.get('line', ''))[:_MAX_LINE_COL_LEN],
        'col': str(data.get('col', ''))[:_MAX_LINE_COL_LEN],
        'context': str(data.get('context', ''))[:200],
        'user_agent': request.headers.get('User-Agent', '')[:300],
    }

    try:
        lines = _safe_read_lines(LOG_PATH)
        lines.append(json.dumps(entry))
        lines = lines[-MAX_ENTRIES:]
        _safe_write_lines(LOG_PATH, lines)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'could not write log: {e}'}), 500

    return jsonify({'ok': True})


@bp.route('/errors', methods=['GET'])
def get_errors():
    limit = request.args.get('limit', 50, type=int)
    try:
        lines = _safe_read_lines(LOG_PATH)
    except OSError as e:
        return jsonify({'ok': False, 'error': f'could not read log: {e}'}), 500
    entries = [json.loads(l) for l in lines[-limit:][::-1] if l.strip()]
    return jsonify({'errors': entries, 'total_logged': len(lines)})


@bp.route('/errors', methods=['DELETE'])
def clear_errors():
    if LOG_PATH.exists() or LOG_PATH.is_symlink():
        LOG_PATH.unlink()
    return jsonify({'ok': True})
