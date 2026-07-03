# What's Unique About Custodian

*The one section to get right in the submission. Everything else is evidence for this.*

---

## The frame (don't sell "spending controls")

Spend caps, approval flows, and audit logs are **commodities** in 2026. Payman,
Skyfire, Catena Labs, Rain, and Ramp all ship them. If we pitch "spending controls
for AI agents," a judge who knows the space hears "me too."

So we don't. We pitch the thing none of them do:

> **Custodian assumes the AI agent is adversarial — it can be wrong, or it can lie —
> and makes the guardrail physically inescapable by enforcing it *below* the agent at
> the OS kernel, not inside a wallet the agent has to be trusted to use correctly.**

That sentence is the whole product. It rests on two pillars no competitor pairs.

---

## Pillar 1 — We treat the agent as a liar, and verify its facts deterministically

Every competitor **trusts the agent's request** and only checks the dollar amount
against a limit. None of them check whether *what the agent claims is even true.*

Custodian's `verify_claims()` layer (deterministic, zero-AI) resolves the agent's
factual assertions against ground truth and flags **CONTRADICTED** before any money
logic runs. The agent does not get to mark its own homework.

**Live proof:** the `06-planted-lie` case. A customer invents a story to get a refund.
The AI agent reads it and recommends *approve*. The verifier catches that the claim is
contradicted by the ledger, and the kernel **overrides the AI**. The money does not move.

No competitor on the list can demonstrate this, because their model is
"agent asks → check the limit," not "agent asks → check if the agent is lying."

This is also **strictly more than the standards cover.** Google's AP2 mandates prove
*the human authorized this agent* (intent). They do **not** prove *the agent's stated
reason is factually true.* Custodian closes the gap AP2 leaves open.

---

## Pillar 2 — We enforce below the agent, not in a wallet it calls

Competitors' control lives in **their custodial cloud**. The agent reaches money by
calling their SDK, and the safety rests on the implicit assumption "it'll use the
approved path."

Custodian's control lives in **Landlock + kernel egress policy** (the same
Landlock-LSM + policy approach NVIDIA's own OpenShell uses). The agent literally
**cannot open a socket** to a payment or provisioning endpoint the OS has not allowed.
The guardrail is not something the agent *invokes* — it is a box the agent is *trapped
inside*.

**Live proof:** the raw OCSF **DENIED** egress log. The agent *tried*, and the kernel
dropped the packet. "It can't even reach the money it isn't authorized to move."

This boundary is also **non-custodial, rail-agnostic, and self-hosted**. We never hold
the funds (Catena wants a bank charter; we want the opposite). The demo used Stripe, but
the kernel doesn't care what's behind the egress rule — swap Stripe for Modal, Azure, or
a bank API and the enforcement is byte-for-byte identical.

---

## The comparison that makes it land

| Capability | Payman / Skyfire / Catena / Rain / Ramp | **Custodian** |
|---|---|---|
| Spend caps / approval / audit | ✅ | ✅ *(table stakes)* |
| Catches the agent **lying** (fact-verification vs ground truth) | ❌ | ✅ |
| Enforcement **below** the agent (kernel egress, not API) | ❌ | ✅ |
| Non-custodial / rail-agnostic / self-hosted | ❌ *(they hold funds)* | ✅ |
| Domain-general (one kernel, **many** decision modules) | ❌ *(money only)* | ✅ |

Only the first row is shared. The bottom four *together* are ours alone right now.

---

## Pillar 3 (the platform) — one kernel, many guardrail modules

Custodian is not a refund bot or a spend bot. The codebase is explicitly built as
**one decision kernel + pluggable policy packs** (`custodian/packs/`). The kernel
decides authority and knows nothing about the domain; a *pack* turns a messy real-world
input into a verifiable request and frames the human escalation.

Two packs ship today on the same kernel — **refunds** (always escalates) and
**purchasing** (clean invoices auto-pay, risky ones escalate). Adding a business
operation is **one registry line plus the pack files** — no change to the engine, the
verifier, or the kernel.

That makes "spend" just the first domain. The same enforcement pattern governs any
consequential agent action: cloud provisioning, payroll, data egress, destructive infra
ops, communications sent as the company. **Money is the demo; the kernel is the product.**

---

## The honest caveat (so we're never blindsided)

Each *ingredient* exists somewhere — OPA/Cedar do policy, sandboxes do egress, AP2 does
intent, Payman does approval. Our novelty is the **synthesis at a specific location**: a
deterministic guardrail kernel that (a) assumes the agent is fallible and verifies its
facts, and (b) sits at the OS boundary so it cannot be bypassed, (c) packaged as a
domain-general module system. A funded competitor *could* add kernel enforcement later —
so this is a real technical head start and an excellent demo wedge, not a patent. We ship
the head start.

---

## How to say it in ten seconds (the judge line)

> "Everyone else gives the agent a constrained **wallet** and trusts it to behave.
> We give the agent a constrained **kernel** — it can't reach money it isn't authorized
> to move, and when it lies to justify a payout, a deterministic verifier catches it and
> overrides the AI. Money is the first module; the kernel governs any decision."
