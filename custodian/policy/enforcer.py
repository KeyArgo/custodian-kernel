"""Enforcement router: DGX Spark node(s) primary, argobox-lite local fallback.

Wraps decide() with a transparent remote-first pattern. Callers import
`decide` from here exactly as they would from evaluator — the signature
is identical. Tries each configured Spark node in order (spark-a, spark-b,
...); if all are unreachable (network blip, host down, reboot), local
enforcement kicks in within a couple seconds with zero visible interruption
to the caller. Spark nodes are known to go down individually — that's what
the chain + local fallback is for; it is not a reason to give up the
separation between enforcement hardware and the app host.

Enforcement mode is configurable at runtime via a flag file
(/tmp/custodian-enforcement-mode). The flag can be set by a dashboard
API endpoint so demo visitors can choose their own enforcement path.
Valid values:
  - "remote-first" (default): try Spark nodes, silently fall back to local
    if all nodes are unreachable.
  - "local": skip Spark entirely, enforce locally.

The flag file is checked at every decide() call, so changes take effect
immediately without a restart.
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

# SPARK_ENFORCE_URLS: comma-separated list, tried in order (spark-a, spark-b, ...).
# SPARK_ENFORCE_URL (singular) is still honoured for backward compatibility if
# SPARK_ENFORCE_URLS is not set. Point this at real hosts as they come online —
# unreachable entries are skipped via the same timeout/fallback path as any
# other outage, so it's safe to list a not-yet-provisioned node in advance.
# Default: spark-a (primary) → spark-b (secondary) → local enforcement on argobox-lite.
_urls_env = os.environ.get('SPARK_ENFORCE_URLS')
if _urls_env is not None:
    SPARK_ENFORCE_URLS = [u.strip() for u in _urls_env.split(',') if u.strip()]
else:
    _url_env = os.environ.get('SPARK_ENFORCE_URL')
    if _url_env is not None:
        SPARK_ENFORCE_URLS = [u.strip() for u in _url_env.split(',') if u.strip()]
    else:
        SPARK_ENFORCE_URLS = [
            'http://10.0.0.50:8095/decide',
            'http://10.0.0.51:8095/decide',
        ]

# Kept for anything importing the old singular name directly (e.g. tests, admin panel).
SPARK_ENFORCE_URL = SPARK_ENFORCE_URLS[0] if SPARK_ENFORCE_URLS else ''
SPARK_TIMEOUT = float(os.environ.get('SPARK_TIMEOUT', '1'))

# Runtime toggle — can be flipped by the admin panel without a restart.
# Also honoured: SPARK_ENFORCE_URLS='' / SPARK_ENFORCE_URL='' env var (disables at startup).
_DISABLE_FLAG = '/tmp/spark-enforcement-disabled'
_remote_enabled = bool(SPARK_ENFORCE_URLS)

# Enforcement mode flag — checked at every decide() call, so changes take effect
# immediately without a restart. Written by the dashboard API endpoint.
_MODE_FLAG = '/tmp/custodian-enforcement-mode'


def _read_mode() -> str:
    """Return current enforcement mode. Defaults to 'remote-first'."""
    try:
        return open(_MODE_FLAG, 'r').read().strip() or 'remote-first'
    except (FileNotFoundError, OSError):
        return 'remote-first'


def set_enforcement_mode(mode: str) -> None:
    """Set enforcement mode to 'remote-first' or 'local'.
    'remote-first' tries Spark nodes then falls back to local.
    'local' skips Spark entirely and enforces locally."""
    if mode not in ('remote-first', 'local'):
        raise ValueError(f'Invalid enforcement mode: {mode!r}')
    try:
        open(_MODE_FLAG, 'w').write(mode + '\n')
    except OSError:
        pass


def enforcement_mode_label() -> str:
    """Human-readable label for the current mode."""
    mode = _read_mode()
    labels = {
        'remote-first': 'Remote-First (Spark → Local)',
        'local': 'Local Only (ArgoBox)',
    }
    return labels.get(mode, f'Unknown ({mode})')


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
    """Quick health probe of every configured node. Returns status dict for the admin panel."""
    if not _remote_enabled:
        return {'enabled': False, 'nodes': [], 'reason': 'no SPARK_ENFORCE_URLS configured'}
    if not spark_enabled():
        return {'enabled': False, 'nodes': [], 'reason': 'disabled by operator'}
    import time
    nodes = []
    for url in SPARK_ENFORCE_URLS:
        try:
            req = urllib.request.Request(
                url.replace('/decide', '/health'),
                headers={'Content-Type': 'application/json'},
            )
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
            ms = round((time.monotonic() - t0) * 1000)
            nodes.append({'url': url, 'reachable': True, 'latency_ms': ms, 'node': data.get('node')})
        except Exception as exc:
            nodes.append({'url': url, 'reachable': False, 'reason': str(exc)})
    return {'enabled': True, 'nodes': nodes, 'reachable': any(n['reachable'] for n in nodes)}


def _try_spark_node(
    url: str,
    request: SpendRequest,
    state: AuthorityState,
    policy: Policy,
    *,
    skill: Optional[str],
    context: dict,
    killed: bool,
) -> Optional[Decision]:
    """Returns a Decision from one Spark node, or None if unreachable."""
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
            url,
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


def _try_spark(
    request: SpendRequest,
    state: AuthorityState,
    policy: Policy,
    *,
    skill: Optional[str],
    context: dict,
    killed: bool,
) -> Optional[Decision]:
    """Tries each configured Spark node in order. Returns the first Decision, or None if all fail."""
    if not spark_enabled():
        return None
    for url in SPARK_ENFORCE_URLS:
        decision = _try_spark_node(
            url, request, state, policy, skill=skill, context=context, killed=killed
        )
        if decision is not None:
            return decision
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
    """Enforce on the first reachable Spark node, otherwise enforce locally.

    Checks the runtime enforcement mode flag: if set to "local", skips Spark
    entirely and enforces locally regardless of Spark availability.
    """
    ctx = context or {}
    # Check enforcement mode — skip Spark if user chose local
    if _read_mode() != 'local':
        decision = _try_spark(request, state, policy, skill=skill, context=ctx, killed=killed)
        if decision is not None:
            return decision
    # All configured Spark nodes unreachable, or mode is local — silent fallback to local enforcement
    return _local_decide(request, state, policy, skill=skill, context=ctx, killed=killed)
