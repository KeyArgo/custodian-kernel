#!/usr/bin/env python3
"""
Create Stripe product + adjustable-quantity payment link for Custodian.
Reads STRIPE_API_KEY from the same secrets file the dashboard uses.
Run this once; the link is permanent.

  python3 scripts/create_product.py
"""
import base64, json, sys, urllib.request, urllib.parse, urllib.error
from pathlib import Path

SECRET_FILES = [
    Path('/tmp/hermes-mount/sandbox/.hermes/secrets/stripe.env'),
    Path('/tmp/hermes-dash-v4/dashboard/secrets/operator.env'),
]

def load_key():
    for f in SECRET_FILES:
        if not f.exists():
            continue
        for line in f.read_text().splitlines():
            for prefix in ('STRIPE_API_KEY=', 'STRIPE_SECRET_KEY='):
                if line.startswith(prefix):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    return None

def stripe_post(path, data, key):
    url = f'https://api.stripe.com/v1/{path}'
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body)
    req.add_header('Authorization', 'Basic ' + base64.b64encode(f'{key}:'.encode()).decode())
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print('Stripe error:', e.read().decode()[:300], file=sys.stderr)
        sys.exit(1)

def main():
    key = load_key()
    if not key:
        print('ERROR: STRIPE_API_KEY not found in secrets files.')
        print('Searched:', [str(f) for f in SECRET_FILES])
        sys.exit(1)

    mode = 'LIVE' if key.startswith('sk_live_') else 'TEST'
    print(f'Stripe mode: {mode}\n')

    # 1. Product
    product = stripe_post('products', {
        'name': 'Custodian AI Safety Review',
        'description': (
            'AI agent governance audit powered by the Custodian kernel. '
            'We run verify_kit against your agent workflow, identify unsafe patterns '
            '(self-approval loops, unbounded spend, missing kill-switch), and deliver '
            'a written safety report with remediation steps.'
        ),
    }, key)
    pid = product['id']
    print(f'Product:  {pid}  ({product["name"]})')

    # 2. Price — $25 each
    price = stripe_post('prices', {
        'product': pid,
        'unit_amount': 2500,
        'currency': 'usd',
        'nickname': 'Safety Review — $25/seat',
    }, key)
    prid = price['id']
    print(f'Price:    {prid}  (${price["unit_amount"]/100:.2f} each)')

    # 3. Payment link — adjustable 1-4 seats (1 seat=$25, 4 seats=$100)
    link = stripe_post('payment_links', {
        'line_items[0][price]': prid,
        'line_items[0][quantity]': 1,
        'line_items[0][adjustable_quantity][enabled]': 'true',
        'line_items[0][adjustable_quantity][minimum]': '1',
        'line_items[0][adjustable_quantity][maximum]': '4',
        'after_completion[type]': 'redirect',
        'after_completion[redirect][url]': 'https://getcustodian.xyz',
        'metadata[source]': 'hackathon-demo',
        'metadata[product]': 'safety-review',
    }, key)
    url = link['url']
    lid = link['id']

    print(f'\n{"="*60}')
    print(f'PAYMENT LINK')
    print(f'{"="*60}')
    print(f'  {url}')
    print(f'\n  Link ID:  {lid}')
    print(f'  Price ID: {prid}')
    print(f'\n  Customer picks 1-4 seats at checkout:')
    print(f'    1 seat  = $25     (solo audit)')
    print(f'    4 seats = $100    (team audit pack)')
    print(f'{"="*60}')
    print(f'\nJudge proof: https://getcustodian.xyz/api/v1/stripe/overview')
    print(f'  (live balance + PaymentIntents, updated every 10s)')

if __name__ == '__main__':
    main()
