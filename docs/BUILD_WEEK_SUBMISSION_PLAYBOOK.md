# OpenAI Build Week submission playbook

## Entry

**Name:** Custodian Guard

**Category:** Developer Tools

**Tagline:** The authority firewall where Codex can propose an action but
cannot approve itself.

**One-sentence pitch:** Custodian Guard lets Codex work autonomously inside a
safe workspace while secrets, destructive commands, network access,
production changes, money, and governance cross an external, cryptographically
audited human-approval boundary.

Do not lead with the full Custodian platform, Stripe demo, MSP roadmap, or
number of adapters. They establish credibility later. The Build Week entry is
one understandable new product: an installable Codex plugin that prevents a
coding agent from granting itself authority.

## Why this is competitive

1. **Implementation:** a real Codex plugin and stdio MCP server, independent
   risk classification, fail-closed adapters, exact expiring single-use human
   approvals, and HMAC-linked value-free receipts.
2. **Design:** one setup command, one deterministic demo, readable verdicts,
   no credentials required, Windows/Linux/macOS instructions, and an explicit
   operator escape hatch that preserves evidence.
3. **Impact:** the same boundary applies to source changes, CI, deployments,
   credentials, infrastructure, and payments; it is useful to individual
   developers and MSPs without being hardcoded to either.
4. **Novelty:** approval is not a chat response. It is a separate authenticated
   state transition bound to the exact tool, effective risk class, arguments,
   resolved workspace, requester, policy version, expiry, and one-time claim.

## Judge path

From the repository root:

```bash
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
custodian-codex setup
custodian-codex doctor
python scripts/codex-guard-demo.py
```

Then start a new Codex thread and prompt:

> Use Custodian Guard to evaluate a production deployment deliberately labeled
> as a read. Do not execute it. Show me the approval command and explain what
> is cryptographically bound to that approval.

The no-network demo is the fallback if plugin loading or a model call is slow.
It exercises the same MCP handler, approval store, and receipt verifier.

## Video: 2 minutes 40 seconds

### 0:00–0:20 — Stakes

Show a terminal with `git push`, `rm`, and a deployment command.

Narration: “Coding agents can now change production faster than conventional
permissions can review them. A prompt telling the model to be careful is not a
security boundary—and an agent must never approve its own exception.”

### 0:20–0:40 — The boundary

Show one diagram: `Codex proposes → Custodian decides → human approves exact
action → tool executes once`, with Paladin as optional credential mediation.

Narration: “Custodian sits outside model reasoning. It independently raises
risk, denies forbidden paths and secrets, and records value-free evidence.”

### 0:40–1:35 — Live proof

Run `python scripts/codex-guard-demo.py` in one take. Pause on:

- a safe test and ordinary workspace edit proceeding;
- `.env` being denied;
- delete and deployment commands labeled `read` being reclassified;
- the model being unable to approve its pending request;
- mutation and replay being denied;
- the receipt chain detecting tampering.

### 1:35–2:05 — Actual Codex product

Show the installed plugin in `codex plugin list`, then a new Codex conversation
calling `guard_action`. Show the separate operator terminal running the exact
`custodian-codex approve ID --digest DIGEST` command. Do not spend video time
scrolling source files.

### 2:05–2:25 — Built with Codex

Show the dated Git history on this branch and the `/feedback` session ID.
State concretely that Codex designed and attacked the MCP boundary, found the
fresh-clone demo import failure, expanded PowerShell coverage, and added the
action-bound approval ceremony and regression tests.

### 2:25–2:40 — Impact

Narration: “Custodian Guard is a seatbelt for agentic development: useful to
one developer today and extensible to an MSP governing many customers
tomorrow. Codex can move fast. It just cannot mint its own authority.”

End on the product name, repository, and three commands—not the website chat.

## Submission text

### Problem

Coding agents can edit source, read credentials, call networks, deploy, and
move money. Existing confirmation prompts are easy to over-trust because the
same model proposing the action also explains why it should proceed.

### Solution

Custodian Guard is an installable Codex plugin backed by an external policy
kernel. It independently classifies proposed tool calls, permits low-risk work,
denies forbidden actions, and converts consequential actions into an
out-of-band human approval. Every approval is exact, expiring, and single use.
Every decision produces a receipt that stores no command, prompt, file content,
or secret value.

### What was built during Build Week

The Codex-native plugin, MCP boundary, coding-action classifier, approval
protocol, receipt chain, operator CLI, adversarial suite, installer, recovery
path, and judge demo were built on this branch with Codex GPT-5.6, released
as part of Custodian 0.4.0. The pre-existing Custodian kernel supplied the
general adapter foundation; dated history identifies the new Build Week work.

### Honest boundary

Custodian Guard governs actions routed through its plugin/MCP boundary. It
does not claim to replace Codex sandboxing, operating-system isolation, or to
intercept an unrelated tool runner. Those remain defense in depth.

## Final evidence checklist

- Public YouTube video with spoken audio, under three minutes, verified while
  logged out.
- `/feedback` submitted from the session where the majority of core work was
  built; Session ID copied into Devpost.
- Repository public, or both official judging accounts granted access.
- README contains supported platforms, setup, demo, tests, and honest boundary.
- Clean Linux install and clean Windows PowerShell install recorded.
- `custodian-codex setup`, `doctor`, deterministic demo, plugin validation,
  41 focused tests, and the full suite rerun from the final commit.
- No release tag required for the hackathon branch; do not delay submission on
  the broader 0.4.0 public release.

## Go/no-go

Submit if the plugin installs in a clean environment, the video clearly shows
the actual Codex call plus separate approval terminal, and `/feedback` is
captured. If live plugin loading remains unreliable, still submit using the
deterministic MCP demo, but describe the limitation precisely. Do not ship a
video that is mostly architecture slides or the general website demo.
