# Custodian

Custodian is a kernel-enforced authority and spend platform for AI agents. An
agent cannot exceed its band or approve its own escalation because the boundary
is enforced outside the agent's own process and outside its own code path —
not by the agent's good behavior.

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

## Tool Layer — 100 governed tools

Custodian ships a governed tool library. Every tool is a Hermes-compatible
skill (SKILL.md frontmatter) that declares a `custodian-band` from L0–L4.
The ToolRegistry auto-discovers them — no registration code needed.

```
custodian tools list              # show all 100 tools grouped by band
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
- 1,110 passing tests, tested with Python 3.13.
- The test suite includes `test_self_approval_regression.py` — a regression
  test for the exact security bug this design prevents. The fix was proven
  by deliberately reintroducing the bug, confirming the test failed, then
  restoring the fix. That test exists so the bug can never silently return.
- Public commit history at `git.argobox.com/KeyArgo/hermes-hackathon-2026`.

**Don't take any of this on faith — run `python3 verify_kit.py` yourself.** One command
re-runs the test suite, actually reintroduces the security bug live to prove the regression
test catches it (then restores the original file), and pulls fresh data straight from the
real public dashboard. See `docs/VERIFICATION.md` for the full manual breakdown too.

## Limitations

- Only one approval backend is shipped: `twilio_verify`. Backends named other
  than `twilio_verify` or `none` are rejected at policy validation time.
- Only one storage backend is shipped: SQLite (via `SqliteStorage`).
- No multi-tenant support. No plugin marketplace. No general-purpose
  expression language in the policy DSL — the match vocabulary is a fixed,
  small set (skill name, context flags, spend-amount threshold).
- No third-party security audit has been performed.
