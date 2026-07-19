# Security Hardening — Paladin, Adapters, Hermes Bridge

This document records the security scan performed while adding the Paladin
credential broker, the guard-adapter framework, and the Hermes bridge
(branch `feat/paladin-adapters-hermes`), the findings, and the design
decisions that make this stack harder to attack than an in-process
guardrail.

## Threat model addition

The existing kernel defends against an agent **exceeding its authority**
(spend caps, bands, kill switch). This work adds defenses against three
further attacker positions:

1. **The agent as credential thief.** An agent (or a prompt-injected
   payload steering it) that tries to read, print, exfiltrate, or
   hard-code an API key.
2. **The agent as saboteur of its own governance.** An agent that edits
   policy, deletes the kill switch, grants itself credentials, or writes
   a new skill to widen its own capability surface.
3. **The context-lossy local model.** Not malicious — just forgetful.
   Repeats spends, loops, calls tools that don't exist, drifts off task.
   These produce real side effects and must be caught mechanically, not
   with a prompt the model has already truncated.

## Scan results on the existing codebase

Patterns audited across `custodian/`, `paladin/`, `integrations/`,
`dashboard/`, `skills/`:

| Check | Result |
|---|---|
| `shell=True` in subprocess calls | none |
| `eval()` / `exec()` on dynamic input | none (only `spec.loader.exec_module` for adapter loading, hash-pinned) |
| `yaml.load` without `SafeLoader` | none (`yaml.safe_load` throughout) |
| `pickle` on untrusted data | none |
| `requests(..., verify=False)` | none |
| committed live secrets | none (only `sk_live_…`/`sk_test_…` as documentation placeholders and prefix checks) |
| MD5 for security | none |

The kernel codebase is clean. Two pre-existing observations were noted
but **not changed** because they sit in other agents' owned paths under
`COORDINATION.md` (bundled skills, backends):

- **F1 — bundled-skill HTTP calls lack timeouts.** ~10 `execute.py`
  scripts under `custodian/bundled_skills/**` and
  `custodian/backends/twilio_verify.py` call `requests.*` without
  `timeout=`. A hung endpoint blocks the skill subprocess up to the
  30-second `invoke()` ceiling — availability only, not integrity. Fix
  is mechanical (`timeout=10`); flagged to the owning lanes.

## Findings addressed in this branch

### F2 — GovernedReceipt integrity is unkeyed (documented + optional fix)

`GovernedReceipt.verify()` recomputes `SHA-256(receipt_id:band:amount:
verdict:output_hash)` and compares. This detects **accidental
corruption** but not **forgery**: anyone who can construct a receipt can
recompute a matching fingerprint, because the hash uses no secret. The
README's phrase "cannot be forged" overstates this.

We did **not** rewrite the kernel receipt (out of scope, and it would
churn the receipt test suite). Instead, receipt *authenticity* is
offered as an opt-in, modular co-signer keyed by the Paladin vault — see
`paladin.receipts.sign_receipt` / `verify_signed`. A verifier who holds
(or is handed) the public verification path can then distinguish a
genuine kernel receipt from a forged one. Sites that need
non-repudiation enable it; the kernel stays lean for those that don't.

### F3 — audit tail-read could silently fork the chain (fixed)

`AuditLog._tail_mac()` originally read a fixed 4096-byte tail. A record
with a long `detail` field could push the final line past that window,
causing `splitlines()[-1]` to return a truncated line, `json.loads` to
throw, and — worse — a naive reader to start a fresh chain from genesis,
breaking tamper-evidence silently. Fixed two ways: the tail window now
grows until it provably contains the last full line, and `detail` is
capped at 512 chars so records stay bounded and value-free. Covered by
`test_paladin.py::test_audit_*`.

### F4 — plaintext secret in the tool process's environment (fixed: sandboxed egress)

The original egress path (`Broker.spawn`) injected resolved secrets into
a child process's **environment** (`subprocess.run(env=...)`). That keeps
the value out of the *proposing agent*, but any code running in the child
— including a prompt-injected tool payload — can read its own
`os.environ` / `/proc/self/environ` and exfiltrate it. Every downstream
control (grants, audit, leak-sentinel) is moot once the child holds the
value. Cyberware has the same class of exposure: its README documents
execution reading secrets from `*_FILE` references in the exec
environment.

Fixed with **sandboxed egress** (`paladin/egress.py`, `paladin/sandbox.py`,
`paladin/egress_client.py`): the child runs under `bwrap --unshare-all`
(no network, fresh namespaces) with the vault directory and keyfile dir
tmpfs-masked and a **rebuilt, minimal environment** (so it cannot inherit
`PALADIN_PASSPHRASE`/`PALADIN_KEYFILE` either). Its only path out is a
read-only-bound Unix socket to an in-process gateway. The child sends an
*unauthenticated* request descriptor; `Broker.egress_request` resolves the
ref (grant-gated + audited), enforces the entry's `allowed_hosts` ceiling
**and** the grant's host/method/path scope (both must pass — the grant
narrows, never widens), attaches the credential, makes the call, and
returns `{status, headers, body}` with the value stripped. **The
credential never enters the child** — verified by
`test_paladin_sandbox.py` (secret absent from the child's env and
`/proc/self/environ`; direct network unreachable; vault files masked).
Fail-closed: if bwrap/userns is unavailable the runner raises rather than
silently falling back to env injection. Scope is HTTP(S)-shaped secrets;
`spawn` env-injection remains for non-Linux and non-request protocols,
with the strong claim gated on the sandbox actually being active.

### F5 — audit hash chain not thread-safe under concurrent egress (fixed)

The egress gateway serves a thread per connection, making it the first
concurrent caller of `AuditLog.append`. Two threads could read the same
tail MAC and append records with the same `prev`, forking the hash chain
(reproduced with 8 threads → `verify()` fails). Fixed by serializing the
read-tail-then-write critical section under a `threading.Lock`
(`paladin/audit.py`); regression covered by
`test_paladin_egress.py::test_concurrent_egress_keeps_audit_chain_intact`.
This guards in-process concurrency; cross-process racing remains the
same separate concern as the vault's save lock.

## Design decisions that raise the security bar

### The agent never holds a credential — even transitively

Cyberware's model is "value-free: data and secrets never transit the
governance layer; they stay in the execution substrate." That keeps
secrets off the *control plane*, but the secrets still live wherever the
agent runs. Paladin goes further: the secret is **encrypted at rest**
(AES-256-GCM, scrypt), and materializes **only inside the skill
subprocess's environment**, built by the broker at egress. The agent
process that proposes the action never has the value in its address
space, never receives it in a tool result (the secret-leak guard redacts
any that come back), and cannot enumerate the vault except as value-free
metadata.
agent runs. Paladin goes further along two rungs. The baseline: the
secret is **encrypted at rest** (AES-256-GCM, scrypt) and materializes
**only inside the skill subprocess's environment**, built by the broker
at egress — the proposing agent never has the value in its address space,
never receives it in a tool result (the secret-leak guard redacts any
that come back), and cannot enumerate the vault except as value-free
metadata. The hardened rung (**sandboxed egress**, F4): the value never
enters the *tool* process either — Paladin holds it and originates the
authenticated call itself, while the tool runs network-isolated with only
a socket to the broker. That is a strictly stronger credential-
confinement claim than either "keep it in the substrate" or "read it from
a `*_FILE` ref."

### Deny-by-default, band-ceilinged, expirable grants

No requester resolves any secret without an explicit grant naming it.
Requesters are exact identities (`skill:stripe-spend`,
`sandbox:hermes-hackathon`) — wildcards are allowed only on the *ref*
side, never the requester side, so you always say precisely *who* gets a
secret. Grants carry a band ceiling and optional TTL. Every resolve and
every denial is written to the hash-chained audit log.

### The agent cannot modify what governs it

`KernelSelfProtection` denies — at any band, with no config override an
agent can reach — writes to the policy, the vault, the kill switch, the
adapter manifest, and the skills tree. An agent authoring a new skill is
an agent minting itself a capability; drafts are forced into a
quarantine dir for human review. This closes the single highest-value
move available to a compromised agent.

### Tamper-pinned adapter installs

Local adapters install with their SHA-256 pinned in the manifest. If the
file changes after install, it **refuses to load** — same stance as the
kernel's `@govern` source-tamper check. Reviewed code is the code that
runs.

### Enforcement survives context loss

Every guardrail that matters (budgets, tool fences, scope, loop
detection) holds its state **outside** the model and enforces at
`pre_action`, independent of whether the model still remembers the rule.
The `SessionCapsule` re-injects an authoritative anchor after any
denial and every N turns, so a forgetful local model is *reminded* — but
enforcement never depends on the reminder landing.

## Residual risk

- Paladin's zeroization is best-effort (CPython may copy bytes); the
  vault key and resolved values live briefly in RAM during egress.
- Sandboxed egress confines the *credential*, not the *data*: a tool
  authorized to call an API can still misuse the response it legitimately
  receives. And if an API echoes the secret in its own response body, the
  child sees it on the way back — the leak-sentinel *detects* that, it
  does not *prevent* it. The strong "credential never enters the process"
  guarantee holds only where the sandbox is active (Linux + unprivileged
  user namespaces) and, for host confinement, where the entry's
  `allowed_hosts` is set — an unrestricted secret can still be sent to any
  host the grant permits.
- The audit chain proves records weren't altered or reordered, but tail
  truncation is only detectable against an external anchor (e.g.
  periodically publishing the tail MAC). This is the same limitation as
  any local append-only log.
- Guard heuristics (injection, secret formats, PII) are recall-oriented,
  not perfect classifiers; they reduce, not eliminate, exposure. They
  compose with the structural defenses above rather than replacing them.
- No third-party audit has been performed on this branch.
