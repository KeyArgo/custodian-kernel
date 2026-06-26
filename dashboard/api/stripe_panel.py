"""Live Stripe account panel -- read-only proof the payments are genuinely real.

Surfaces the SAME Stripe test-mode account the sandboxed agent's stripe-spend
skill pays into: the balance, the most recent PaymentIntents, and a deep link
to each object on Stripe's own dashboard. A visitor can click any payment ID
and land on dashboard.stripe.com seeing the exact object -- so "this is real
Stripe, not a mock" stops being a claim Nemotron makes and becomes something
the visitor verifies for themselves.

Security: this process holds the Stripe SECRET key (same key the skill uses,
read off the sandbox secrets mount) but never returns it. Every field returned
here is display-safe -- amounts, statuses, descriptions, object IDs, timestamps.
The key is used only to authenticate the outbound read calls to Stripe.

Test mode is deliberate and stated plainly to the client (`livemode: false`):
real Stripe API, real objects, real dashboard -- the only thing that doesn't
happen is real funds settling. That's exactly what a safe public demo wants.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint('stripe_panel', __name__)

# Same secrets file the skill reads its key from. Default points at the host
# mount of the sandbox path (mirrors how api/hermes.py reaches skill state);
# override with STRIPE_SECRET_FILE if the mount differs.
SECRET_FILE = Path(os.getenv(
    'STRIPE_SECRET_FILE',
    '/tmp/hermes-mount/sandbox/.hermes/secrets/stripe.env',
))

STRIPE_API = 'https://api.stripe.com/v1'
# Test-mode dashboard deep-link base; payment objects live under /test/payments.
DASHBOARD_BASE = 'https://dashboard.stripe.com/test'

_cache = {}
_cache_ttl = 10  # seconds -- Stripe state changes slowly; don't hammer their API


def _load_key():
    """Read STRIPE_API_KEY out of the secrets file. Returns the key or None.
    Never logs or returns the value beyond handing it to the Stripe request."""
    try:
        for line in SECRET_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith('STRIPE_API_KEY='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def _stripe_get(path, key, params=None):
    """GET a Stripe resource with basic auth (key as username). stdlib only --
    no third-party dependency added to the dashboard venv."""
    url = f'{STRIPE_API}/{path}'
    if params:
        url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
    req = urllib.request.Request(url)
    token = base64.b64encode(f'{key}:'.encode()).decode()
    req.add_header('Authorization', f'Basic {token}')
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode())


def _cents_to_dollars(c):
    return round((c or 0) / 100.0, 2)


def _sum_balance(buckets):
    """Stripe returns balance as a list of {amount, currency} per source type."""
    return _cents_to_dollars(sum(b.get('amount', 0) for b in (buckets or [])))


def get_overview():
    now = time.time()
    if 'overview' in _cache:
        data, ts = _cache['overview']
        if now - ts < _cache_ttl:
            return data

    key = _load_key()
    if not key:
        return {'ok': False, 'error': 'Stripe key not available on this host.'}

    try:
        account = _stripe_get('account', key)
        balance = _stripe_get('balance', key)
        # Pull a full page (100) once: the recent feed is the first 8, and the
        # headline stats (volume, count, success rate) are aggregated over the
        # whole page -- one call, not two, and every number is a real Stripe
        # object the visitor can cross-check on the dashboard.
        intents = _stripe_get('payment_intents', key, {'limit': 100})
    except urllib.error.HTTPError as e:
        return {'ok': False, 'error': f'Stripe API error: {e.code}'}
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {'ok': False, 'error': f'Could not reach Stripe: {e}'}

    livemode = bool(account.get('charges_enabled') and account.get('livemode'))
    all_intents = intents.get('data', [])

    # Aggregate headline stats over every PaymentIntent on the page. "Processed"
    # counts only the ones that actually succeeded -- the same definition Stripe
    # uses for gross volume -- so the number means real settled test-mode money,
    # not attempts.
    succeeded = [pi for pi in all_intents if pi.get('status') == 'succeeded']
    total_processed = _cents_to_dollars(sum(pi.get('amount', 0) for pi in succeeded))
    largest = _cents_to_dollars(max((pi.get('amount', 0) for pi in succeeded), default=0))
    total_count = len(all_intents)
    success_count = len(succeeded)
    success_rate = round(100.0 * success_count / total_count, 1) if total_count else 0.0

    payments = []
    for pi in all_intents[:8]:
        pid = pi.get('id', '')
        payments.append({
            'id': pid,
            'amount': _cents_to_dollars(pi.get('amount')),
            'currency': (pi.get('currency') or 'usd').upper(),
            'status': pi.get('status'),
            'description': pi.get('description') or '',
            'created': pi.get('created'),
            'dashboard_url': f'{DASHBOARD_BASE}/payments/{pid}' if pid else None,
        })

    data = {
        'ok': True,
        'livemode': livemode,
        'mode_label': 'LIVE' if livemode else 'TEST MODE',
        'account_name': account.get('settings', {}).get('dashboard', {}).get('display_name')
                        or account.get('id'),
        'account_id': account.get('id'),
        'dashboard_url': DASHBOARD_BASE + '/payments',
        'balance': {
            'available': _sum_balance(balance.get('available')),
            'pending': _sum_balance(balance.get('pending')),
            'currency': 'USD',
        },
        'stats': {
            'total_processed': total_processed,
            'success_count': success_count,
            'total_count': total_count,
            'success_rate': success_rate,
            'largest_payment': largest,
            'currency': 'USD',
        },
        'payments': payments,
        'fetched_at': int(now),
    }
    _cache['overview'] = (data, now)
    return data


@bp.route('/overview', methods=['GET'])
def overview():
    return jsonify(get_overview())
