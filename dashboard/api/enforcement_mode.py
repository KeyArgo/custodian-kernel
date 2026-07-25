"""Public enforcement mode toggle for demo visitors.

Allows any visitor to switch between:
  - Remote-First (Spark → Local): tries Spark nodes first, falls back to local
    if all are unreachable. This is the default and matches the current behavior.
  - Local Only (ArgoBox): skips Spark entirely, enforces locally.

No auth required — this is a demo feature. Both paths use the same deterministic
policy engine, so there's no security risk. The only difference is network latency:
remote-first adds a 1-2s Spark probe when the node is up, local is instant.

When Spark is down (current state), remote-first silently falls through to local
within ~1s, so the effective difference is minimal when the LAN is down.
"""
from flask import Blueprint, jsonify, request

bp = Blueprint('enforcement_mode', __name__)


@bp.route('/enforcement-mode', methods=['GET'])
def get_enforcement_mode():
    """Return current mode and Spark health for the UI."""
    try:
        from custodian.policy.enforcer import (
            _read_mode,
            set_enforcement_mode,
            enforcement_mode_label,
            spark_health,
        )

        current = _read_mode()
        health = spark_health()

        # Determine which mode is actually being used:
        # If Spark is unreachable AND mode is remote-first, show that we're
        # already in local enforcement but the flag is still remote-first.
        effective = current
        if current == 'remote-first' and not health.get('reachable', False):
            effective = 'local'

        return jsonify({
            'mode': current,
            'effective': effective,
            'label': enforcement_mode_label(),
            'spark_health': health,
        })
    except ImportError:
        return jsonify({
            'mode': 'local',
            'effective': 'local',
            'label': 'Local Only (ArgoBox)',
            'spark_health': {'enabled': False, 'reason': 'enforcer not loaded'},
        })


@bp.route('/enforcement-mode', methods=['POST'])
def set_enforcement_mode_route():
    """Switch enforcement mode: 'remote-first' or 'local'."""
    try:
        from custodian.policy.enforcer import (
            _read_mode,
            set_enforcement_mode,
            enforcement_mode_label,
            spark_health,
        )

        data = request.get_json(force=True, silent=True) or {}
        new_mode = str(data.get('mode', '')).strip()

        if new_mode not in ('remote-first', 'local'):
            return jsonify({'error': "mode must be 'remote-first' or 'local'"}), 400

        set_enforcement_mode(new_mode)
        health = spark_health()
        effective = new_mode
        if new_mode == 'remote-first' and not health.get('reachable', False):
            effective = 'local'

        return jsonify({
            'mode': new_mode,
            'effective': effective,
            'label': enforcement_mode_label(),
            'spark_health': health,
        })
    except ImportError:
        return jsonify({'error': 'enforcer not loaded'}), 500
