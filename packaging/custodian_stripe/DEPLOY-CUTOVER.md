# Deploy cutover — not yet executed

`custodian_stripe/` (this monorepo's copy, see `custodian-repos.json`/build
script) currently exists alongside, not instead of, the Stripe skill still
running live inside `custodian-dev`'s original locations. Nothing about the
live `getcustodian.xyz/operator` demo has been touched — this note describes
what would need to happen to actually point it at this package, for whenever
that's a deliberate decision rather than something done blind.

## Current live wiring (unchanged)

`dashboard/api/operator.py` shells out via `nemohermes <sandbox> exec` to
fixed scripts at `/sandbox/.hermes/skills/payments/stripe-spend/scripts/`
inside the running NemoClaw sandbox. Nothing touched during this work changes
how that path gets populated — that mechanism lives outside both locations
(however the sandbox is provisioned) and wasn't identified during this
session.

Also still untouched and still depending on the original in-repo skill path:
- `custodian/packs/refunds/extractor.py` (hardcoded path to
  `skills/payments/stripe-spend/references/refund-policy.md`)
- `tests/test_stripe_spend_core.py` (imports `_core.py` from
  `skills/payments/stripe-spend/scripts/` by exact relative path,
  monkeypatching module-level functions — this pinning is why
  `execute_spend`/`execute_earn`/`execute_refund` were deliberately NOT
  rewired to use the new `PaymentProcessor` interface)
- `dashboard/api/stripe_panel.py` / `dashboard/api/stripe_webhook.py` — these
  are independent, hand-rolled Stripe integrations for the live dashboard;
  they don't import from either skill copy, so they're unaffected by any of
  this either way

## Steps to actually cut over

1. Confirm how `/sandbox/.hermes/skills/payments/stripe-spend/scripts/`
   currently gets populated (a provisioning script, a manual copy, a mount —
   unconfirmed as of this note).
2. Point that mechanism at this monorepo's `custodian_stripe/skills/payments/stripe-spend/`
   instead of the original `custodian/bundled_skills/payments/stripe-spend/` /
   `skills/payments/stripe-spend/` copies.
3. Repoint `custodian/packs/refunds/extractor.py`'s hardcoded path.
4. Move `tests/test_stripe_spend_core.py`'s import target to the
   `custodian_stripe/` copy.
5. Re-run the full live demo arc (earn → spend → approve → kill-switch →
   refund) against the cutover copy before considering it live — real
   Stripe test-mode charges, real Twilio SMS, so this needs a human watching.
6. Only after that's confirmed working, delete the now-redundant
   `custodian/bundled_skills/payments/stripe-spend/` and
   `skills/payments/stripe-spend/` from this repo — until then, both copies
   staying in sync is a known, accepted duplication, not a bug.
7. Only after 1-6 are done and verified, publish the public mirror
   (`keyargo/custodian-stripe`) via the same release-tree + publish-mirror.sh
   flow as kernel/codex-guard.

## What already works today, independent of this cutover

- `custodian_stripe` (in-repo) imports directly against this repo's own
  `custodian.processors.base` / `custodian.authority.ledger` — no external
  kernel release needed for local development. Its own eventual release
  wheel is built by `scripts/build-custodian-stripe-release-tree.py` against
  `packaging/custodian_stripe/pyproject.toml`, which declares the real
  external `custodian-kernel>=0.4.0,<0.5` dependency for external installers.
- `custodian setup --with stripe` and the kernel's tool registry pick this
  package's skills/component up automatically via entry-point discovery,
  verified end-to-end (11 stripe-related tools surfaced with zero
  special-casing in the kernel) before this migration.
- `StripeProcessor` (`custodian_stripe/processor.py`) is a real, tested
  implementation of the kernel's vendor-neutral `PaymentProcessor` interface,
  independent of anything in the live-deployed skill scripts.
