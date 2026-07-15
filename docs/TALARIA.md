# Talaria — the Hermes Agent + NemoClaw integration suite

Named for Hermes' winged sandals. Talaria is the one call surface
between Hermes Agent and everything Custodian offers — every
Hermes/NemoClaw-specific assumption lives here, not in the kernel. The
kernel (`custodian/`), the guard-adapter framework (`custodian/adapters/`),
and the credential broker (`warden/`) are all brand-neutral and know
nothing about Hermes; Talaria is what wires them together specifically
for it. A future Claude or Codex integration would be its own equivalent
package, resting on the same neutral core.

## Quickstart — protect your local Hermes Agent in one command

```bash
pip install custodian-kernel[warden]

talaria hermes install          # installs the guard plugin + starter policy + vault
hermes plugins enable talaria-guard
```

That's it. Every tool call your Hermes Agent makes now runs through the
guard pipeline first. Out of the box it will:

- **block reads and writes** to `~/.ssh`, `~/.aws`, `~/.gnupg`, `*.env`,
  `*.pem`, private keys (edit `~/.talaria/policy.yaml` to change);
- **block secret leaks** — the model cannot write a real credential to a
  file or send one in a tool call (proven live: it tried five evasion
  techniques and every one was caught);
- **block prompt-injection** payloads riding in tool arguments;
- **stop forbidden tools** — list them in `policy.yaml` and the model
  literally cannot call them, no matter how it's prompted;
- **log every blocked attempt** to a tamper-evident record:

```bash
talaria log            # timeline of everything the agent tried but wasn't allowed
talaria log verify     # confirm the record hasn't been altered
talaria log --csv      # export
talaria hermes status  # what's active
```

### The rules live in one file — `~/.talaria/policy.yaml`

```yaml
tools:
  forbid: [stripe-payout]        # the agent can NEVER call these
  # allow: [read_file, write_file, shell]   # if set, ONLY these

paths:
  forbid: ["~/.ssh", "~/.aws"]   # never read OR write these
  forbid_globs: ["*.env", "*.pem", "id_rsa"]
  # allow: ["~/projects/workspace"]   # or confine to a workspace

privacy:
  redact: [email, phone, ssn, card]

log_denials: true
```

Rules are enforced **mechanically on every call** — the model can't talk
its way around a guard the way it can ignore a system-prompt instruction.

## Credentials — the broker

```bash
talaria vault add stripe_sk --env-var STRIPE_SECRET_KEY   # same broker as `warden`
talaria vault list
talaria vault exec --with stripe_sk -- ./charge.py        # value injected into the child only
```

`talaria vault ...` and the standalone `warden ...` command are the exact
same broker underneath — nothing is duplicated, `talaria vault` just
saves a Hermes user from needing to know a second tool name. The agent
only ever holds a `warden://stripe_sk` reference; the real value is
injected into the tool subprocess's environment at the last moment and
never enters the agent's own process.

## Session / spend governance — a second, separate compiler

The quickstart above (`~/.talaria/policy.yaml` → `build_pipeline()` →
the Hermes plugin) is the everyday "keep the agent out of my files and
secrets" surface. For the fuller case — kernel spend bands, a budget,
workspace/host confinement, skill authoring — there's a second,
independent YAML + compiler: `hermes-session.yaml` → `build_bridge()`
(in `talaria/session_policy.py`) → a `HermesBridge`. These are not
layered on top of each other; pick whichever surface matches what
you're protecting. `build_bridge()` is not wired into the
`talaria hermes install` plugin path — it's used by embedding a
`HermesBridge` directly (see the Python example below).

```bash
talaria init hermes-session.yaml --goal "keep the homelab healthy"
talaria adapters list
talaria session status  ./hermes-session.capsule.json
talaria session anchor  ./hermes-session.capsule.json
```

Every skill invocation flows:

```
Hermes proposes  invoke(skill, args)
  → guard adapters (pre): confabulation, injection, self-protection,
    scope, loops, spend anomalies, PII
  → capability adapters may answer directly (introspection meta-skills)
  → kernel decide: band / cap / envelope / kill switch
  → Warden egress: credentials materialize ONLY in the skill subprocess
  → skill executes
  → guard adapters (post): secret redaction, PII redaction
  → SessionCapsule records what happened
Hermes receives the (possibly transformed) result + an anchor when needed
```

## One YAML declares everything Hermes may do

```yaml
goal: "keep the homelab healthy"
band: L2
budget_usd: 25.00
constraints:
  - "never touch production databases"

tools:
  allow: [http-get, stripe-spend, file-read, file-write]   # omit = all
  forbid: [stripe-payout]

files:
  workspace: /srv/agent-workspace          # writes fenced here
  skill_quarantine: /srv/agent-workspace/skill-drafts

network:
  hosts: [api.stripe.com, integrate.api.nvidia.com]

money:
  max_per_minute: 4
  duplicate_window_s: 900

privacy:
  redact: []          # empty = redact every kind pii-redactor knows about

guards:               # togglable; set false to drop one.
  repetition: true     # self_protection/prompt_injection/secret_leak are
  pii: true             # NOT listed here — they're kernel-grade and
  introspection: true  # always on, not settable via policy.
```

```python
from talaria.session_policy import build_bridge
from warden.vault import Vault
from warden.broker import Broker

broker = Broker(Vault.open(passphrase=...))
bridge = build_bridge("hermes-session.yaml", broker=broker)

result = bridge.invoke("stripe-spend", {"amount": 5.0, "description": "credits"})
```

The YAML can only **narrow** safe defaults — there is no key that turns
off the kernel or the confabulation check. This is the granular control
requested: what tools Hermes can call, what skills it may author (drafts
go to quarantine for human review), what files it can edit, what hosts it
can reach, how fast and how much it can spend.

## Deep skill integration

The bridge runs against the same `ToolRegistry` that powers the 100+
governed skills on the website — no adapter shims per skill. Any skill
with a `custodian-band` in its `SKILL.md` is automatically fenced,
budgeted, credentialed (via Warden), and audited.

Three **meta-skills** are served by the governance layer itself (the
`hermes-introspection` capability adapter), so Hermes can inspect its own
governed state:

- `custodian-status` — band, budget spent/remaining, action/denial counts.
- `custodian-anchor` — the full re-anchoring block on demand.
- `warden-vault-list` — which `warden://` refs exist (metadata only).

## Local models that lose context

The `SessionCapsule` keeps goals, constraints, band, budget, and a
rolling action history **outside** the model, persisted to disk. After
any denial and every N turns, the bridge attaches an authoritative
`anchor` block to the result — restating the invariants *and* what
already happened ("you already refunded this order") — which the Hermes
loop prepends to the next model turn. Enforcement never depends on the
reminder landing: the `context-anchor` guard denies out-of-bounds actions
whether or not the model still remembers the rule.

## SOUL.md that matches the policy

`talaria/soul.compile_soul_section(policy_path, capsule)`
renders the authority section of the Hermes system prompt *from* the live
policy, so what the model is told always equals what the kernel enforces
— no drift between a hand-written "$2 cap" and a policy that says $5.

## NemoClaw egress

`talaria/nemoclaw_egress.governed_sandbox_exec(...)` runs a
script inside a NemoClaw sandbox with Warden-resolved secrets piped in
over stdin — never on the command line, never written to sandbox disk,
grant-gated under `sandbox:<name>` and audited.

## How this compares to BlindKey

[BlindKey](https://github.com/michaelkenealy/blindkey) is the closest
peer — an early-stage tool for making AI agents blind to API keys. Talaria
matches its feature set and goes further:

| | BlindKey | Talaria + Custodian |
|---|---|---|
| Agent never sees plaintext secrets | ✅ `bk://` | ✅ `warden://` |
| AES-256-GCM encrypted vault | ✅ | ✅ |
| Hash-chained tamper-evident audit | ✅ | ✅ (`warden audit`, `talaria log verify`) |
| Content scanner (secrets + PII) | ✅ | ✅ (secret-leak-guard, pii-redactor) |
| Filesystem gating (allow + deny, **read & write**) | ✅ | ✅ (path-fence) |
| Domain allowlist (secret only to approved hosts) | ✅ | ✅ (egress-domain-guard) |
| Denial log of blocked attempts, exportable | ✅ | ✅ (`talaria log`, JSON/CSV) |
| **Prompt-injection guard** on tool args | ❌ | ✅ |
| **Tool denylist** (model *cannot* call forbidden tools) | ❌ | ✅ (enforced, not prompted) |
| **Spend / money-authority governance** (bands, caps, kill switch, escalation) | ❌ | ✅ (the Custodian kernel) |
| **Context-loss re-anchoring** for drifting local models | ❌ | ✅ (`SessionCapsule`) |
| **Pluggable, hash-pinned third-party guards** | ❌ | ✅ (adapter framework) |
| **Proven live** blocking a real agent's evasion attempts | prototype (3★, no releases) | ✅ (blocked 5 techniques against a running Hermes session) |
| Native integration | OpenClaw + Claude Desktop (MCP) | Hermes Agent (plugin) + NemoClaw |

The short version: BlindKey protects *credentials* for HTTP calls.
Talaria protects credentials **and** stops the agent from touching
forbidden files/tools, catches injection, governs money, keeps a
context-lossy local model on-task, and proves each block with a
tamper-evident receipt — all enforced below the model, not asked of it.

Follow-on (not yet shipped): a web dashboard and an MCP server for the
Claude Desktop audience — both on the roadmap, Hermes is the current lane.
