# custodian-stripe

Stripe payment-processor adapter for [Custodian](https://getcustodian.xyz), the
kernel-enforced safety and authority layer for AI agents.

Custodian's kernel defines a vendor-neutral `PaymentProcessor` interface
(`custodian.processors.base`) so that letting an agent move real money never
requires the kernel itself to know anything about a specific payment vendor.
This package is the Stripe implementation of that interface — the thing you
install if you want an agent's spend/refund/payout requests, once the kernel
has decided to allow them, to actually go through Stripe.

It ships as its own package, separate from `custodian-kernel`, on purpose:
installing the kernel never pulls in Stripe, a Stripe API key, or any
payment-specific assumptions unless you explicitly ask for them. A future
adapter for a different processor (Square, PayPal, ...) would be its own
equivalent package, following the same pattern.

## Status

This package targets kernel functionality (`custodian.processors`,
`custodian.authority.ledger`) that is not yet in a published
`custodian-kernel` release. Until a kernel release containing those modules
ships, installing this package's dependency on `custodian-kernel` will not
give you a working `PaymentProcessor` base to import against — check the
kernel's own changelog before relying on this in production.

The live getcustodian.xyz demo still runs on the original in-kernel copy of
the Stripe skill during this transition — see `DEPLOY-CUTOVER.md` for the
plan to actually cut it over once this package is verified end to end.

## What's in here

- `custodian_stripe/processor.py` — `StripeProcessor`, implementing
  `charge()` / `refund()` / `payout()` / `balance()` against the real Stripe
  API via the official `stripe` Python SDK. Idempotency keys are passed
  through to Stripe's own idempotency handling, so a retried call can't
  double-charge. A failed Stripe call raises rather than reporting false
  success.
- `custodian_stripe/skills/` — the Stripe skill scripts (raw API skills like
  balance/refund-list/payout, plus the authority-gated stripe-spend skill)
  for use with a Custodian-governed agent runtime. Discovered automatically
  by the kernel's tool registry once this package is installed — no manual
  wiring required.
- `custodian_stripe/setup.py` — registers this package so `custodian setup
  --with stripe` picks it up automatically.

## Install

```bash
pip install custodian-stripe
```

This pulls in `custodian-kernel` (the `PaymentProcessor` interface this
package implements) and the official `stripe` SDK.

## Usage

```python
from custodian_stripe.processor import StripeProcessor

processor = StripeProcessor(api_key="sk_test_...")  # or set STRIPE_API_KEY
result = processor.charge(
    amount=10.50, currency="usd",
    description="order #1234", idempotency_key="order-1234-charge-1",
)
print(result.id, result.status)
```

In practice, most users won't call `StripeProcessor` directly — it's the
thing the Custodian kernel's authority gate calls on your behalf once a
proposed spend has been evaluated and allowed.

## Development

This package's source lives inside the `custodian-dev` monorepo at
`custodian_stripe/`, alongside the kernel it depends on, so during
development it's imported directly (no separate install needed — see the
root `pyproject.toml`'s `packages.find`). Its standalone release wheel is
assembled by `scripts/build-custodian-stripe-release-tree.py` using this
directory's `pyproject.toml`, and published separately once verified.

```bash
python -m pytest tests/test_custodian_stripe_processor.py tests/test_custodian_stripe_entry_points.py -v
```

Tests fully mock the `stripe` SDK — no real network calls, no real API key
needed to run the test suite.

## License

Apache-2.0 — see [LICENSE](../../LICENSE).
