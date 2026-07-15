# Design: the single-use authorization primitive

Status: **draft for review.** Targets ROADMAP-cyberware.md §2.3, reused by
§1.1 (egress) and §3.3 (quote binding).

## 0. Correction to the roadmap's baseline

The roadmap states the primitive's egress version is **already built**
("host/method/path-scoped grants", reused three times → "build once, apply
three times"). Verified against the code: **it does not exist, in any form.**

What actually exists is two unrelated things:

| | `paladin/grants.py` (`Grant`) | `custodian/adapters/builtin/egress_domain_guard.py` |
|---|---|---|
| Scope | `ref_pattern` + `requester` + `max_band` | `{secret_name: [host]}` — **host only**, no method, no path |
| Lifetime | **Standing** policy, reusable | Standing config map |
| Single-use | **No** — only `revoke()`; no nonce, no consume | No |
| Shape | Dataclass in the vault | Adapter config |
| Package | `paladin` | `custodian` |

A grep for `single_use|nonce|consume|at_most_once` across the whole tree
returns only AES-GCM encryption IVs in `paladin/crypto.py` — unrelated to
authorization replay.

So: **there is no single-use authorization anywhere, and no method/path
scoping anywhere.** This is net-new work, not reuse. The dependency-spine
argument ("build once, apply twice") survives, but as a *plan*, not as a
already-paid cost. Phase 2.3 is bigger than the roadmap prices it.

Accurate by contrast: §1.5's claim that "empty `allowed_hosts` = any host" is
a real hole — `egress_domain_guard.py:13` confirms "An empty/absent host list
means unrestricted."

## 1. The crux: single-use ≠ at-most-once

The roadmap treats these as one property. They are two, with different
mechanisms, and conflating them is how you ship a double-charge.

- **Single-use** is *local*: this authorization burns after one redemption.
  A local `UNIQUE` constraint gives it.
- **At-most-once** is *end-to-end*: the side effect happens on the rail no
  more than once, including across crashes and retries. A local burn **cannot**
  give this, because the failure that matters is *not knowing whether the
  charge landed*.

Today's live bug is exactly this gap. `custodian/bundled_skills/payments/
stripe-spend/scripts/_core.py:114-125` POSTs `payment_intents`, catches
`RequestException` (which includes `Timeout`, at `timeout=10`), sleeps 1s, and
POSTs **again with no idempotency key**. If the first POST landed and only the
response was lost, that is a second charge. No idempotency handling exists
anywhere in the tree.

A naive burn-then-charge makes this *worse*, not better:

| Order | Crash point | Result |
|---|---|---|
| burn → charge | after burn | Authorization dead, charge never happened. Fails closed, but the spend is unrecoverable without minting a new authorization — and the operator can't tell if it charged. |
| charge → burn | after charge | Authorization still live. **Double-charge on retry.** |

Neither is acceptable. At-most-once requires the rail to deduplicate, which
means the retry must carry **the same idempotency key** as the original.

## 2. The design: reserve → complete, key-carrying

Redemption is **not a boolean burn**. It is a durable intent record with a
state machine, and the nonce *is* the rail idempotency key.

```
mint ──▶ AUTHORIZED ──reserve()──▶ RESERVED ──▶ COMPLETED   (rail confirmed)
                                      │
                                      ├──▶ FAILED       (rail rejected — terminal)
                                      └──▶ RESERVED     (crash/timeout — retry
                                                         re-sends SAME key)
```

- `reserve()` is the atomic step: it inserts the nonce and durably records the
  idempotency key **before** any network call. Crash after this point is
  recoverable, because the key survives.
- The charge always sends `Idempotency-Key: <nonce>`. A retry after any
  ambiguous failure re-sends the identical key; Stripe returns the *original*
  result rather than charging again. That is where at-most-once actually comes
  from — the rail, not us.
- Only an unambiguous rail response moves `RESERVED → COMPLETED|FAILED`. A
  timeout is **ambiguous** and must stay `RESERVED` for retry, never be
  marked failed.

The single most important rule: **ambiguity is not failure.** Marking a
timed-out charge `FAILED` and minting a fresh authorization is how you
double-charge with a correct-looking state machine.

## 3. Atomicity

`custodian/storage/sqlite.py` already exists, so the primitive should live
there rather than invent a store:

```sql
CREATE TABLE authorization_redemption (
  nonce           TEXT PRIMARY KEY,   -- also the rail idempotency key
  requester       TEXT NOT NULL,
  scope_hash      TEXT NOT NULL,      -- binds this record to one exact action
  state           TEXT NOT NULL,      -- RESERVED | COMPLETED | FAILED
  rail_ref        TEXT,               -- e.g. Stripe pi_...
  reserved_at     REAL NOT NULL,
  completed_at    REAL
);
```

`reserve()` = `INSERT` inside a transaction. The `PRIMARY KEY` makes concurrent
double-reserve structurally impossible — the second `INSERT` raises
`IntegrityError`, which is the *correct* behaviour (deny), not an error to
swallow. This is the whole single-use guarantee; it needs no locking.

Note `paladin/vault.py` currently hand-rolls file locking (`fcntl`/`msvcrt`) —
do **not** repeat that here. SQLite's transaction is the atomicity primitive.

## 4. Scope binding

`scope_hash` binds the authorization to one exact action so an authorization
minted for one charge cannot be redeemed for another. It is a canonical hash
over the domain's scope fields — not a free-form dict.

The honest generalization boundary — **the lifecycle generalizes, the scope
does not**:

| | Egress (§1.1) | Spend (§2.3) | Quote (§3.3) |
|---|---|---|---|
| Scope fields | host, method, path | amount, currency, recipient, rail | plan_hash |
| Rail dedupe | n/a (idempotent GET) or replay window | Stripe `Idempotency-Key` | n/a — local only |
| Ambiguity | retry is usually safe | retry **must** carry the key | n/a |

So the shared artifact is a **lifecycle + a `Scope` interface**, not one
concrete primitive with three configs. Each domain implements
`Scope.canonical_bytes()`; the mint/reserve/complete machinery is shared.
Realistically that is ~60% reuse, not 100% — and the egress case does **not**
need the reserve→complete dance at all, because there is no money to
double-spend. Forcing egress through the money-grade state machine would be
over-engineering; it needs mint + burn + scope check only.

This is worth saying plainly because it weakens the roadmap's sequencing
argument: **§2.3 does not actually depend on §1.1 being done first.** The
shared part is a base class. Money can be built first.

## 5. Decimal interaction (§2.1)

`scope_hash` covers `amount`. If amount is a `float`, the hash is
float-formatting-dependent and two logically equal amounts can hash
differently — the authorization silently fails to match. **The scope must hash
`Decimal` minor units as an integer**, never a float. So §2.1 (Decimal) is a
hard prerequisite of §2.3, which the roadmap's dependency spine does not list.

Verified: `custodian/types.py` declares `amount: float` at lines 55, 139, 198,
and `ledger.py:36` does `round(total, 2)` over float sums. Six files named by
§2.1 all exist.

## 6. Naming

The package is `paladin`, renamed from its previous name on branch
`refactor/warden-to-paladin`. This design writes `paladin.*` throughout.

The rename kept one deliberate exception, which matters to this design: the
old name survives as a **read-only compatibility surface** — the legacy ref
scheme, the legacy vault home and filename, and the legacy env vars. The rule
applied there is the one to keep applying here:

> **Silent failures get a compatibility shim; loud ones don't.**

A missing CLI command fails loudly and was allowed to break. A vault that
quietly resolves to an empty directory, or a ref that a guard no longer
recognizes as a secret, fails *silently* — and in the guard's case, open. Those
got shims. When this primitive gains persisted state, the same test applies:
ask what an old record does when the new code meets it, and whether anyone
finds out.

## 7. Open questions

1. **Who mints?** If the agent can mint its own spend authorization, the
   primitive is theatre. Minting must sit behind the same authority the band
   ceiling uses — probably `policy/enforcer.py`. Unresolved.
2. **Reconciliation.** `RESERVED` records that never complete need a sweeper
   that asks Stripe the truth (by idempotency key) rather than guessing.
   Without this, at-most-once holds but *at-least-once* silently doesn't.
3. **Expiry vs. reserve.** An authorization that expires while `RESERVED` must
   still honour its retry — expiry gates `reserve()`, never `complete()`.

## 8. Proposed first cut

Independent of Phase 1, ordered by risk retired per hour:

1. Add `Idempotency-Key` to the two `_core.py` Stripe POSTs. One line each;
   kills the live double-charge today.
2. `amount: float → Decimal` (six files, minor units).
3. `Scope` interface + `Authorization` lifecycle + the SQLite table above.
4. Wire spend through mint → reserve → charge → complete.
5. Egress scope (host/method/path) on the mint+burn path only.
