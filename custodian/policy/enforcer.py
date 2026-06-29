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
SPARK_TIMEOUT = float(os.environ.get('SPARK_TIMEOUT', '2'))

# Set SPARK_ENFORCE_URL='' to disable remote and always use local.
_remote_enabled = bool(SPARK_ENFORCE_URL)


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
    if not _remote_enabled:
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
                'session_spent': state.session_spent,
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
