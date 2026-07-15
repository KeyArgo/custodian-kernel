# Roadmap: catch and pass Cyberware

Priority order (fixed): **1) security  2) money  3) everything else, better.**
This order is not just preference — it is the technical critical path (see
"Dependency spine" at the end): the separate signing principal built for
security is a hard prerequisite for signed money-metering, and the single-use
authorization primitive built for money is reused by the skill economy.

## Honest baseline (where we actually stand)

Verified against both codebases, not marketing:

**We already lead on:** credential confinement (the credential never enters
the tool process — `paladin exec --sandbox`, tested), enforced network egress
(child has no network but the broker socket), context-loss enforcement
(SessionCapsule/anchors), non-custodial spend governance, and modular
hash-pinned adapters.

**Cyberware leads on:** a separate signing OS principal (`exod`, Ed25519-signs
each result), ledger depth (Merkle checkpoints + Go cold verifier +
crypto-shred), formal verification (TLC + Apalache + TLAPS), signed +
transparency-logged distribution with mutual binary re-measurement, and a
built-out economy (quote → escrow → metered payout → lineage royalties).
Caveat: their strongest isolation tier (delegated `exod`, SV-3) is the part
their *own repo* flags least-mature; their default cooperative mode still
binds secrets into the executing process.

**Our money core today** (`custodian/` — bands, per-action + session caps, 24h
rolling envelope, margin gate, no-self-dealing, spend-sentinel adapter,
receipts, Stripe skills, Twilio escalation) is real governance but has two
concrete weaknesses this roadmap targets: **every amount is a `float`** (no
`Decimal` — latent currency-rounding bugs, and precisely Cyberware's stated
edge) and there are **no settlement-integrity primitives** (no idempotency,
at-most-once, conservation, or escrow).

---

## PHASE 1 — SECURITY: make the credential lead unbeatable, close their two edges

Turn the thing we already lead on into an airtight, *proven* boundary, and
neutralize Cyberware's two strongest security differentiators.

**1.1 Separate-principal egress + signed results (the `exod` answer).**
Run the egress gateway as its own OS principal (dedicated uid / dropped-priv
process), not in-process same-uid. Give it an Ed25519 key; every egress result
and every denial is signed, and the audit chain records the signature — so
"the only status trusted is the isolated principal's signature," matching
`exod` for the credential path. **This is also the foundation for signed
money-metering in Phase 2 — build it here.**

**1.2 Sandbox tier ladder.** Today: `bwrap --unshare-all`. Add: run as
non-root inside (uid 65534, matching their "nobody"), a seccomp + Landlock
profile (L3), and an optional Firecracker/cloud-hypervisor microVM tier (L4)
for high-risk bands. Tier selected by band, fail-closed.

**1.3 Hostile red-team corpus (the proof).** Promote the ad-hoc adversarial
checks into a permanent suite covering credential attacks (env/`/proc`/memory/
socket/CRLF/redirect/SSRF/DNS-rebind), egress bypass (direct socket, alt HTTP
client, subprocess, namespace escape), authorization (replay, scope-widen,
cross-run reuse, TOCTOU, request-mutation-after-approval), and audit
(reorder/truncate/fork/concurrent). This is what lets us say "tested, not
asserted" — the exact claim Cyberware advertises.

**1.4 Signed, transparency-logged distribution.** cosign-sign wheels/sdists +
container images, publish to a transparency log (Sigstore/Rekor), and add
mutual binary re-measurement between principals on connect (their SV-4).
Table-stakes credibility they have and we don't.

**1.5 SSRF / metadata default-deny.** The gateway denies link-local, cloud-
metadata, and RFC1918 destinations by default unless explicitly allowed —
closing the one real hole in today's "empty `allowed_hosts` = any host"
semantics.

**Exit:** separate signing principal + signed egress results + red-team corpus
green + signed releases. We now *match* their isolation story and *exceed* on
credential confinement, both proven.

---

## PHASE 2 — MONEY: from governance gates to provably-correct settlement

Cyberware settles inside its own closed escrow. We govern **real rails**
(Stripe/etc.), non-custodial, with the structural guarantees they have **plus
the ones they lack**. Only start after Phase 1 (2.4 depends on 1.1).

**2.1 Exact-decimal money core (correctness foundation).** Migrate every
`amount: float` → `Decimal` across `types.py`, `receipt.py`, `ledger.py`,
`policy/envelope.py`, `policy/margin.py`, `policy/evaluator.py`. Currency-aware
(minor units), explicit rounding policy (banker's rounding). Property tests
that sums conserve to the cent. This is a real latent-bug fix *and* erases
Cyberware's "exact decimal, no floats" advantage.

**2.2 Conservation-checked double-entry ledger.** Every spend becomes two
entries (debit envelope / credit rail); the ledger enforces that the books
balance and totals reconcile — money is never silently created or destroyed.
Beats Cyberware by doing it over real external rails, not a closed economy.

**2.3 Single-use, plan-bound spend authorizations (reuse the egress primitive).**
A spend is authorized for exactly ONE charge — bound to amount + currency +
recipient + rail + nonce + expiry, single-use, at-most-once. This is the
direct money analog of the host/method/path-scoped egress grant already built
in Phase 1's lineage; **build the primitive once, apply it to both.** Thread
idempotency keys to Stripe so a retry cannot double-charge even across a crash.
Replay / duplicate-charge becomes structurally impossible — their "pays out at
most once," but for real rails.

**2.4 Signed metering from the isolated principal (depends on 1.1).** The
separate signing principal signs the meter: billed on the isolated principal's
signed meter, never the agent's stopwatch — directly matching `exod`-signed
metering, enabled essentially for free by Phase 1.

**2.5 Signed receipts by default + external anchoring (beat their TSA receipts).**
Make `paladin.receipts` HMAC co-signing the **default** for money receipts (not
opt-in), upgrading the kernel's unkeyed SHA-256 fingerprint (finding F2). Add an
external timestamp/transparency anchor (RFC-3161 TSA and/or Rekor) so completion
receipts are non-repudiable against an independent clock — matching their
"TSA-anchored receipts" and going further with public transparency.

**2.6 Non-custodial-first, escrow-optional settlement.** Keep never-hold-funds
as the default (we authorize *your* Stripe). Add an *optional* escrow adapter
for funds-held-until-delivery flows, with the same at-most-once payout
guarantee — so we can do escrow when asked without being locked into custody
like Cyberware.

**2.7 Merchant-grade guardrails (where we go way beyond).** Velocity limits,
per-recipient caps, refund/chargeback governance, anomaly detection (extend
spend-sentinel's loop detection), multi-party approval thresholds, per-project/
per-agent/per-customer envelopes, and a real-time spend view (extend the
talaria dashboard). Cyberware meters; it does not do merchant risk management.

**Exit:** exact-decimal, double-entry-conserved, single-use-authorized,
signed-metered, externally-anchored, non-custodial-with-optional-escrow, plus
merchant guardrails. Genuinely "way way better at money" than a closed metering
economy.

---

## PHASE 3 — PARITY-PLUS: everything else Cyberware does, better

Only after 1 and 2. Each item maps to one of their security/verification tiers.

**3.1 Ledger depth: Merkle checkpoints + cold verifier (their SV-2).**
Merkle-checkpoint the audit/ledger so history cold-verifies in O(tail); ship a
standalone verifier in a second language (Go/Rust) for a trust-minimized second
implementation, mirroring their Go cold verifier. Crypto-shred support (drop a
subject's AES-GCM key without breaking the chain) — we already use AES-GCM.

**3.2 Selective formal verification (their SV-5, aimed better).** Do NOT chase
workflow-deadlock TLA+ (it strengthens neither security nor money). DO write a
TLA+/Apalache spec of the invariants that matter: **settlement conservation**
(money never created/destroyed) and **at-most-once payout**. Machine-checking
the *money* invariants is a stronger, more relevant story than deadlock-freedom
and directly backs Phase 2's claims.

**3.3 Skill economy: quote → deliver → settle → lineage (their SV-6).** Itemized
quotes bound to a plan hash, delivery-gated settlement, lineage/royalty
attribution — over real rails, non-custodial. Reuse the single-use authorization
(2.3) as the quote-binding primitive.

**3.4 microVM tier + mutual attestation (their SV-3/SV-4 top rungs).** Productize
the Firecracker tier from 1.2; principals re-measure each other's live binary on
connect and fail closed on a one-byte change.

**3.5 Positioning + external audit.** Rewrite the head-to-head as a full
tier-by-tier table showing match-and-exceed on each, and commission a
third-party security audit — the one credibility marker neither project has,
and the decisive one.

---

## Cross-cutting principles
- Every phase ends with a real **adversarial** corpus, not just unit tests.
- No "100% / unbypassable" language anywhere — "tested, fail-closed, here is the
  exact residual risk." That honesty is itself a differentiator.
- **Reuse primitives:** the scoped, single-use *egress grant* (security) and the
  plan-bound, single-use *spend authorization* (money) are the same primitive.
  Build once, apply twice.
- Keep the package boundaries: `custodian` ⊥ `paladin` ⊥ `talaria`. Money core
  stays in `custodian`, credential/signing in `paladin`, integration in
  `talaria` (enforced by `test_architecture_boundaries.py`).

## Dependency spine (why this exact order)
1. **Security first is the critical path, not just the preference.** Phase 1.1's
   separate signing principal is a hard prerequisite for Phase 2.4's signed
   metering.
2. **Money before economy.** Phase 2.3's single-use authorization primitive is
   reused by Phase 3.3's skill-economy quotes.
3. **Build money before verifying it.** Phase 3.2's formal verification targets
   Phase 2's conservation and at-most-once invariants — they must exist first.
