# Hermes Bridge

The bridge is the one call surface between Hermes Agent and everything
Custodian offers. Every skill invocation flows:

```
Hermes proposes  invoke(skill, args)
  → guard adapters (pre): confabulation, injection, self-protection,
    scope, loops, spend anomalies, PII
  → capability adapters may answer directly (introspection meta-skills)
  → kernel decide: band / cap / envelope / kill switch
  → Caduceus egress: credentials materialize ONLY in the skill subprocess
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
  redact: [email, phone, ssn, card]

guards:            # all default true — set false to drop one
  prompt_injection: true
  secret_leak: true
  repetition: true
  self_protection: true
  introspection: true
```

```python
from integrations.hermes.session_policy import build_bridge
from caduceus.vault import Vault
from caduceus.broker import Broker

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
budgeted, credentialed (via Caduceus), and audited.

Three **meta-skills** are served by the governance layer itself (the
`hermes-introspection` capability adapter), so Hermes can inspect its own
governed state:

- `custodian-status` — band, budget spent/remaining, action/denial counts.
- `custodian-anchor` — the full re-anchoring block on demand.
- `caduceus-vault-list` — which `caduceus://` refs exist (metadata only).

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

`integrations/hermes/soul.compile_soul_section(policy_path, capsule)`
renders the authority section of the Hermes system prompt *from* the live
policy, so what the model is told always equals what the kernel enforces
— no drift between a hand-written "$2 cap" and a policy that says $5.

## NemoClaw egress

`integrations/hermes/nemoclaw_egress.governed_sandbox_exec(...)` runs a
script inside a NemoClaw sandbox with Caduceus-resolved secrets piped in
over stdin — never on the command line, never written to sandbox disk,
grant-gated under `sandbox:<name>` and audited.
