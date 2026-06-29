# Custodian

Don't take this on faith. Verify from pip in 90 seconds:

```bash
pip install custodian-kernel
custodian demo-verify
```

That command hits the live system, runs 4 claim-verification scenarios, and
shows CONTRADICTED/VERIFIED in real time — no credentials, no cloning.

For the full test suite: `pip install custodian-kernel[dev] && pytest tests/`

This is the only hackathon entry where a judge can verify every security
claim from a single `pip install`.

## Features

### Core
- 1,254+ tests, 0 failures (network tests excluded)
- Deterministic claim verifier (CONTRADICTED / VERIFIED / UNVERIFIABLE)
- Operator-only kill switch with resume logic
- Authority bands L0-L4 with per-request caps
- Real Stripe PaymentIntent on record (`pi_3TkZWEPfSF4TGXT90AWlrnle`)
- Real Twilio SMS escalation
- Self-approval regression test (proves the kernel fix)
- 100 governed tools in `custodian/bundled_skills/`

### CLI Commands
- `custodian request` — spend decision with policy evaluation
- `custodian audit` — full audit ledger
- `custodian demo-verify` — 4 claim-verification scenarios (no creds)
- `custodian earn-and-buy` — closes the economic cycle on camera (no creds)
- `custodian status-banner` — one-screen kernel state (totals + last 5)
- `custodian poison-tests` — 5 planted-bad-claim tests (no creds)
- `custodian beancount` — export ledger to Beancount v2
- `custodian confirm <id>` — post-action confirm (60s deadline)

### Policy Directives (all opt-in)
- `daily_envelope: $50` — rolling 24-hour cap per band
- `margins: { minimum_margin: $0.10, minimum_margin_pct: 20 }` — refuse if margin too low
- `band_after_task: L0` — auto-downgrade after a skill completes
- `policies: { no_self_dealing: true }` — block self-paying agents

### Verify Kit
- `python3 verify_kit.py` — 4-phase self-verifying proof
  - Regresses the self-approval bug live
  - Pulls fresh dashboard + Stripe data
  - Runs the full test suite
  - Tests the kill switch end-to-end
- `custodian demo-verify` — 4 claim-verifier scenarios
- `custodian poison-tests` — 5 attack patterns the kernel catches
- `custodian earn-and-buy` — full economic cycle (earn → gate → spend → verify)

## What Custodian is

Custodian is a kernel-enforced authority and spend platform for AI agents.

An agent cannot exceed its band or approve its own escalation because the
boundary is enforced outside the agent's own process and outside its own code
path — not by the agent's good behavior.

The agent submits a spend request. The policy engine decides: autonomous
(within your configured band, no human needed) or escalation (over the cap,
human approval required via Twilio Verify). The agent never holds the keys to
both sides of that decision, so self-approval is structurally impossible, not
just discouraged.

**New here? Read [`docs/WHAT_THIS_IS.md`](docs/WHAT_THIS_IS.md) first** — a plain-language
walkthrough of what this actually does, why it needs AI in exactly one place and nowhere
else, and a worked real example end to end.

**Wondering what this is actually for beyond one demo?** See
[`docs/BUSINESSES_THIS_UNLOCKS.md`](docs/BUSINESSES_THIS_UNLOCKS.md) — the same enforcement
pattern applied to five concrete, named business shapes, not just the one shown here.

## Installation

```bash
pip install custodian-kernel
```

For development (clone first):

```bash
pip install -e ".[dev]"
```

## Quickstart

```bash
# Scaffold a workspace
custodian init --dir myagent

# Edit the generated policy.yaml to configure authority bands
# (see docs/POLICY_LANGUAGE.md)

# Autonomous request (under the $2.00 default cap)
custodian request --amount 1.00 --description "API credits"

# Escalation request (over the cap — will warn about missing Twilio config)
custodian request --amount 50.00 --description "Server upgrade"

# Check authority state
custodian status

# View audit log
custodian audit
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — design, flow diagram, privilege separation model
- [Policy Language](docs/POLICY_LANGUAGE.md) — complete YAML format reference
- [Security](docs/SECURITY.md) — threat model, self-approval fix, verification model
- [Verification](docs/VERIFICATION.md) — how to check every claim yourself
- [Getting Started](docs/GETTING_STARTED.md) — 10-minute walkthrough

## Tool Layer — 102 governed tools

Custodian ships a governed tool library. Every tool is a Hermes-compatible
skill (SKILL.md frontmatter) that declares a `custodian-band` from L0–L4.
The ToolRegistry auto-discovers them — no registration code needed.

```
custodian tools list              # show all 102 tools grouped by band
custodian tools run http-get --url https://example.com
custodian tools summary           # JSON band breakdown
```

**Tool categories:**

| Category | Count | Band | Example |
|---|---|---|---|
| Utilities | 8 | L0 | base64, hash-sha256, url-parse, json-transform, timezone, currency-convert |
| Web | 5 | L0–L1 | http-get, http-post, web-scrape, web-search, news-search |
| Files | 3 | L0–L1 | file-read, file-list, shell-exec (read-only allowlist) |
| Memory | 5 | L0 | kv-get/set/delete/list, sqlite-query |
| Scheduling | 5 | L1 | task-queue-add/list, cron-create/list/delete |
| Communication | 6 | L1–L2 | email-send, sms-send, slack-message, discord-webhook, webhook-post, push-notification |
| Docker | 4 | L1–L2 | docker-list, docker-logs, docker-start, docker-stop |
| GitHub | 3 | L0–L1 | github-file-read, github-issue-create, github-pr-list |
| NVIDIA NIM | 4 | L2 | nim-model-list, nim-job-submit, nim-job-status, nim-cost-estimate |
| Stripe (extended) | 8 | L2–L3 | stripe-balance, stripe-customer-lookup, stripe-invoice, stripe-refund |
| Financial AI | 5 | L2–L3 | modal-run, huggingface-infer, openai-complete, anthropic-complete |
| Calendar | 5 | L1–L2 | calendar-list, calendar-create, calendar-update |

Tools with missing credentials return `{"ok": false, "stub": true}` — the
framework works without any env vars configured; stub tools show in the registry
with their band and description so the capability surface is visible during review.

### Authority bands

| Band | Policy | Use case |
|---|---|---|
| L0 | Always autonomous, no spend | Read-only data fetching |
| L1 | Autonomous, trivial side effects | Creating records, sending low-stakes messages |
| L2 | Autonomous up to per-action cap | AI inference, Stripe calls under threshold |
| L3 | Always escalates to operator | Refunds, subscription changes, payouts |
| L4 | Always escalates, unlimited scope | Reserved for future high-stakes tools |

## What's real right now

- A real Stripe (test-mode) PaymentIntent is on record:
  `pi_3TkZWEPfSF4TGXT90AWlrnle` — confirm it at Stripe's own API or dashboard.
- A real Twilio Verify integration sends SMS approval codes to an operator's
  phone. The code is never written to any file the agent can read.
- A real, operator-only kill switch (`custodian kill --by <name>` / `custodian
  resume --by <name>`) is wired into the live, authoritative `spend.py` —
  not a separate demo path. Verified live: a real autonomous spend succeeded,
  the kill switch was engaged, the exact same request was denied by the real
  script running inside the live sandbox, then released, then the real spend
  succeeded again. The full sequence is in the real audit log.
- 1,239 passing tests (4 network-dependent tests deselected by default), tested with Python 3.11+.
- The test suite includes `test_self_approval_regression.py` — a regression
  test for the exact security bug this design prevents. The fix was proven
  by deliberately reintroducing the bug, confirming the test failed, then
  restoring the fix. That test exists so the bug can never silently return.
- Public commit history at `github.com/KeyArgo/custodian-kernel`.

**Don't take any of this on faith.** Everything verifiable from pip:

```bash
pip install custodian-kernel       # install the kernel
custodian demo-verify              # live claim check against the running system
pip install custodian-kernel[dev] && pytest tests/   # 1,239 tests, 0 failures
git clone https://github.com/KeyArgo/custodian-kernel  # read every line
```

See `docs/VERIFICATION.md` for the full manual breakdown.

## Limitations

- Only one approval backend is shipped: `twilio_verify`. Backends named other
  than `twilio_verify` or `none` are rejected at policy validation time.
- Only one storage backend is shipped: SQLite (via `SqliteStorage`).
- No multi-tenant support. No plugin marketplace. No general-purpose
  expression language in the policy DSL — the match vocabulary is a fixed,
  small set (skill name, context flags, spend-amount threshold).
- No third-party security audit has been performed.
