# Custodian vs. Cyberware — head to head

Cyberware (`github.com/rhCat/cyberware`, `cyberware.systems`) is the
closest thing to a peer: an AI-agent governance runtime where "the agent
proposes; nothing runs except through cyberware," with cryptographic
verification and tamper-evident ledgers. This is an honest, feature-level
comparison — not marketing — of where we match it and where we go
further, with **security** as the deciding axis.

## Where cyberware is genuinely strong

- **Two-phase govern/run** with a value-free execution plan; delegated
  execution sandboxed via bubblewrap/gVisor on Linux nodes.
- **Skill economy**: itemized quotes, exod-signed metering, escrow-gated
  payout, lineage royalties, TSA-anchored completion receipts.
- **Authenticity everywhere**: chip validated at boot, signed Docker
  images, keyless cosign, ~1,200 tests, self-regenerating CI.
- **Value-free control plane**: "data and secrets never transit"
  cyberware — they stay in the execution substrate.

We take these seriously. The economy and the TSA-anchored receipts are
real advantages worth matching over time.

## Where Custodian already matches

| Capability | Cyberware | Custodian |
|---|---|---|
| Agent proposes, layer decides, nothing runs otherwise | ✅ | ✅ (`@govern`, middleware, bridge) |
| Tamper-evident ledger / provenance | ✅ | ✅ (hash-chained Paladin audit; kernel receipts) |
| Deterministic pre-execution scanning | ✅ (oversight regex) | ✅ (guard-adapter pipeline) |
| Skill model with self-tests | ✅ (perks) | ✅ (SKILL.md + registry, 100+ governed) |
| Sandbox execution | ✅ (bubblewrap/gVisor) | ✅ (NemoClaw executor + bwrap network-isolated egress) |
| ~1,200+ tests, CI-gated | ✅ | ✅ (1,640 passing) |

## Where Custodian goes further — and is more secure

### 1. Secrets are encrypted, and the credential never enters the tool process

Cyberware is *value-free*: secrets never cross the control plane, but
they still live in the execution substrate — its README documents
execution reading them from `*_FILE` references in the exec environment.
**Custodian + Paladin encrypts secrets at rest** (AES-256-GCM, scrypt) and
materializes them under a deny-by-default, band-ceilinged, expirable
grant. The proposing agent never has the value in its address space, can't
enumerate the vault beyond value-free metadata, and any secret that comes
*back* in tool output is hash-matched and redacted before the model sees
it.

The hardened path goes one rung further than *anything Cyberware
documents*: **sandboxed egress** (`paladin exec --sandbox`) runs the tool
under `bwrap --unshare-all` with no network except a Unix socket to the
broker, the vault masked, and a rebuilt environment. The tool sends an
unauthenticated request descriptor; Paladin attaches the credential
host-side and returns only the response. So the key is not in a `*_FILE`,
not in an env var, not in the tool's memory at all — and the tool can't
reach any host the grant didn't scope, because it can't reach the network
directly. This is verified, not asserted: `test_paladin_sandbox.py`
confirms the secret is absent from the child's env and
`/proc/self/environ` and that direct network egress is unreachable. Honest
scope: HTTP(S)-shaped secrets, Linux + unprivileged user namespaces, and
fail-closed when that isn't available.

### 2. The agent cannot modify what governs it

`kernel-self-protection` denies — at any band, with no override an agent
can reach — writes to policy, the vault, the kill switch, the adapter
manifest, and the skills tree. Authoring a new skill is minting a
capability, so drafts are quarantined for human review. This closes the
highest-value move available to a compromised agent.

### 3. Enforcement survives context loss (built for local models)

Cyberware's oversight is a scan; it doesn't model the *forgetful* agent.
Custodian's `context-anchor`, `repetition-breaker`, and
`tool-confabulation-guard` hold their state outside the model and enforce
mechanically, while the `SessionCapsule` re-anchors a drifting local
model with authoritative state ("you already did this"). This is the
whole local-AI safety story, and it's ours.

### 4. Everything is a modular adapter, not a monolith

Guard, money, privacy, and capability behaviors are all adapters — enable
exactly what you want, install third-party packs via entry points, or
drop in a local adapter that's **SHA-256 hash-pinned** and refuses to
load if edited. Cyberware's oversight is more centralized; ours is
composable down to the individual check.

### 5. Non-custodial and rail-agnostic

Cyberware settles through its own escrow/ledger. Custodian is
non-custodial: it governs spend around *your* Stripe/Modal/NIM accounts
and never holds funds. Fewer trust assumptions, no platform lock-in.

## Honest gaps to close

- **Metered skill economy.** Cyberware's quote → escrow → metered payout
  → lineage-royalty pipeline is more built-out than ours. This is the top
  roadmap item to match.
- **TSA-anchored receipts.** Our audit chain proves ordering and
  authenticity locally; an external time-stamp anchor would strengthen
  non-repudiation. `paladin.receipts` co-signing is the first step.
- **Signed distribution.** Cyberware ships cosign-verified images; we
  should sign releases the same way.

## The one-line summary

Cyberware keeps secrets *out of the control plane* (but in the execution
substrate, read from `*_FILE` refs). Custodian keeps the credential *out
of the tool process entirely* — encrypted at rest, materialized only
host-side behind a network-isolated sandbox — stops the agent from editing
its own governor, and keeps enforcing when a local model forgets the rules,
while staying non-custodial and modular down to each check. On security,
that's a wider moat.
