"""Enforcement router: DGX Spark primary, argobox-lite local fallback.

Wraps decide() with a transparent remote-first pattern. Callers import
`decide` from here exactly as they would from evaluator — the signature
is identical. If the Spark enforcement node is unreachable (network blip,
kronos outage, reboot), local enforcement kicks in within 2 seconds with
zero visible interruption to the caller.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from custodian.policy.evaluator import decide as _local_decide
from custodian.policy.schema import Policy
from custodian.types import AuthorityState, Band, Decision, SpendRequest, Verdict

SPARK_ENFORCE_URL = os.environ.get(
    'SPARK_ENFORCE_URL', 'http://192.168.50.56:8095/decide'
)
SPARK_TIMEOUT = float(os.environ.get('SPARK_TIMEOUT', '1'))

# Runtime toggle — can be flipped by the admin panel without a restart.
# Also honoured: SPARK_ENFORCE_URL='' env var (disables at startup).
_DISABLE_FLAG = '/tmp/spark-enforcement-disabled'
_remote_enabled = bool(SPARK_ENFORCE_URL)


def spark_enabled() -> bool:
    """True if Spark enforcement is active. Checks the runtime flag file."""
    return _remote_enabled and not os.path.exists(_DISABLE_FLAG)


def spark_disable() -> None:
    """Disable Spark enforcement at runtime. Survives until spark_enable() or restart."""
    open(_DISABLE_FLAG, 'w').close()


def spark_enable() -> None:
    """Re-enable Spark enforcement at runtime."""
    try:
        os.remove(_DISABLE_FLAG)
    except FileNotFoundError:
        pass


def spark_health() -> dict:
    """Quick health probe. Returns status dict for the admin panel."""
    if not _remote_enabled:
        return {'enabled': False, 'reachable': False, 'reason': 'SPARK_ENFORCE_URL not set'}
    if not spark_enabled():
        return {'enabled': False, 'reachable': None, 'reason': 'disabled by operator'}
    import time
    try:
        req = urllib.request.Request(
            SPARK_ENFORCE_URL.replace('/decide', '/health'),
            headers={'Content-Type': 'application/json'},
        )
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
        ms = round((time.monotonic() - t0) * 1000)
        return {'enabled': True, 'reachable': True, 'latency_ms': ms, 'node': data.get('node')}
    except Exception as exc:
        return {'enabled': True, 'reachable': False, 'reason': str(exc)}


def _try_spark(
    request: SpendRequest,
    state: AuthorityState,
    policy: Policy,
    *,
    skill: Optional[str],
    context: dict,
    killed: bool,
) -> Optional[Decision]:
    """Returns a Decision from the Spark node, or None if unreachable."""
    if not spark_enabled():
        return None
    try:
        payload = json.dumps({
            'request': {
                'amount': request.amount,
                'description': request.description,
            },
            'state': {
                'band': state.band.value,
                'per_action_cap': state.per_action_cap,
                'session_cap': state.session_cap,
                'session_spent': state.spent_this_session,
            },
            'killed': killed,
            'skill': skill,
            'context': context,
        }).encode()
        req = urllib.request.Request(
            SPARK_ENFORCE_URL,
            data=payload,
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(req, timeout=SPARK_TIMEOUT) as resp:
            data = json.loads(resp.read())
        verdict = Verdict(data['verdict'])
        band = Band(data['band']) if data.get('band') else policy.default_band
        return Decision(
            verdict=verdict,
            request=request,
            reason=data.get('reason', ''),
            band=band,
        )
    except (urllib.error.URLError, OSError, TimeoutError, KeyError, ValueError):
        return None


def decide(
    request: SpendRequest,
    state: AuthorityState,
    policy: Policy,
    *,
    skill: Optional[str] = None,
    context: Optional[dict] = None,
    killed: bool = False,
) -> Decision:
    """Enforce on DGX Spark if reachable, otherwise enforce locally."""
    ctx = context or {}
    decision = _try_spark(request, state, policy, skill=skill, context=ctx, killed=killed)
    if decision is not None:
        return decision
    # Spark unreachable — silent fallback to local enforcement
    return _local_decide(request, state, policy, skill=skill, context=ctx, killed=killed)
