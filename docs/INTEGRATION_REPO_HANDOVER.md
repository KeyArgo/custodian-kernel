# Custodian integration repositories — implementation handover

## Objective

Turn Custodian into a provider-neutral governance platform with independent,
native integrations for Hermes, Codex, Claude Code, and Google Antigravity.
Each integration must use the same enforceable action contract, optional
Paladin credential flow, and verifiable receipts without adding provider
dependencies or website-specific behavior to the kernel.

Do not tag or publish Custodian 0.4.0 until the owner explicitly approves the
release. Preserve backward compatibility throughout the extraction.

## Final repository names

| Repository | Python/package identity | Responsibility |
|---|---|---|
| `inovinlabs/custodian-kernel` | `custodian` | Provider-neutral policy engine, guard adapters, action contract, verdicts, receipt interfaces, and conformance tests. |
| `inovinlabs/paladin-vault` | `paladin` | Provider-neutral encrypted vault, grants, value-free audit, credential broker, and egress restrictions. |
| `inovinlabs/talaria` | `talaria` | Thick Hermes Agent/NemoClaw operating integration: hooks, governed invocation, session capsules, re-anchoring, Paladin injection, denial log, dashboard, and sandbox egress. |
| `inovinlabs/custodian-codex` | `custodian_codex` | Codex plugin, governance skill, MCP server, Codex action classifier, optional Paladin mediation, receipt tools, and judge demo. |
| `inovinlabs/custodian-claude` | `custodian_claude` | Claude Code plugin/hooks that route consequential tool calls through the shared Custodian contract. |
| `inovinlabs/custodian-antigravity` | `custodian_antigravity` | Google Antigravity-native adapter using the same contract; intended to support the Gemini/GCP XPRIZE business. |

Use the `inovinlabs` GitHub organization consistently. Do not use `KeyArgo`
for the canonical product repositories unless the owner explicitly changes
the organization decision.

## Dependency direction — mandatory

```text
custodian-kernel       paladin-vault
       ▲                    ▲
       └────────┬───────────┘
                │
      integration repositories
    talaria / codex / claude / antigravity
```

- `custodian-kernel` must never import Paladin or any provider integration.
- `paladin-vault` must never import Custodian or any provider integration.
- Integration repositories may depend on both.
- Integrations must not depend on one another.
- `getcustodian.xyz` is a consumer. No kernel or integration may contain its
  routes, credentials, deployment configuration, or operator-specific prompts.
- A model sees `paladin://name` references and metadata only. Secret values may
  materialize only inside a grant-authorized execution environment.

## What remains in `custodian-kernel`

- `ActionContext`, adapter protocol, pipeline, and provider-neutral guards.
- Stable verdict vocabulary: autonomous, escalation required, denied.
- Provider-neutral coding/action risk categories where they are genuinely
  reusable, not Codex-specific command aliases.
- Receipt protocol and verification interfaces.
- Integration conformance suite: every adapter must prove fail-closed errors,
  no risk-label downgrade, secret-value absence, scope enforcement, and receipt
  tamper detection.
- Optional compatibility shims for the former monorepo imports for at least one
  release cycle.

## What moves out

### `talaria`

Move the current `talaria/` package and its tests. Talaria is deliberately the
thick integration because it owns more of the Hermes/NemoClaw runtime:

- Hermes `pre_tool_call` and result-transform hooks;
- `HermesBridge` governed invocation;
- session capsule and context-loss re-anchoring;
- Paladin reference discovery and grant-gated subprocess injection;
- NemoClaw sandbox egress;
- denial log and local management dashboard;
- `talaria hermes install`, policy, and vault convenience commands.

### `custodian-codex`

The initial implementation currently lives on branch `feat/codex-guard` in
`/home/dev/custodian-dev`. Move these components after the Build Week
checkpoint is committed and pushed:

- `plugins/custodian-codex-guard/`
- `custodian/codex_guard/` (rename package to `custodian_codex` after extracting)
- `scripts/codex-guard-demo.py`
- `tests/test_codex_guard.py`
- Codex-specific portions of `docs/CODEX_GUARD.md`

The kernel-side `PathFence(base_path=...)` improvement is provider-neutral and
must remain in `custodian-kernel`.

### `custodian-claude`

Build only after Codex is submitted. Use Claude Code's native hook/plugin
surface to translate tool proposals into the shared action contract. Do not
copy the classifier, receipts, or Paladin logic; depend on shared interfaces.

### `custodian-antigravity`

First verify Antigravity's current official extension/tool interface rather
than guessing it. Build it as a client of the same bridge. For XPRIZE it is a
supporting interface for the Gemini/GCP-powered MSP business, not the business
or submission by itself.

## Immediate priority: OpenAI Build Week

Submit `custodian-codex` in the Developer Tools category. The entry is:

> Custodian Guard for Codex — a capability firewall that lets Codex work
> autonomously inside safe boundaries while secrets, destructive operations,
> network access, production changes, money movement, and governance changes
> deny or stop for human approval. Value-free HMAC-chained receipts prove every
> decision.

Current implementation status on `feat/codex-guard`:

- Codex plugin manifest and governance skill implemented and validated.
- Dependency-free stdio MCP server with `guard_action` and `verify_receipts`.
- Typed risk model and independent risk inference.
- Caller cannot disguise `rm`, `git push`, `curl`, or deployment as a read.
- Workspace, `.env`, credential, prompt-injection, and kernel-self-protection
  guards composed fail-closed.
- Value-free HMAC hash-chained receipts and tamper test.
- Deterministic no-network judge demo.
- `1,975 passed, 1 skipped, 4 deselected` full repository run.
- Wheel and source distribution build successfully.
- Plugin validator passes.

Still required before submission:

1. Add optional, grant-gated Paladin discovery/use to the Codex MCP integration.
   Codex must see references only, never values.
2. Complete a clean built-wheel install test. A previous venv inherited the
   editable checkout and skipped installation because the version was already
   present; recreate it without that contamination or force-reinstall safely.
3. Install the MCP server in Codex and test it from a fresh Codex thread.
4. Confirm the Build Week session used GPT-5.6 and record its `/feedback`
   session ID.
5. Commit and push the branch. Do not tag a release.
6. Record a public YouTube video with spoken audio, under three minutes.
7. Ensure the public README explains what Codex built and distinguishes dated
   new work from the existing kernel.
8. Submit before July 21, 2026 at 5:00 PM PDT.

## Codex Paladin design

Do not expose a generic `get_secret` tool. Provide metadata-only discovery and
an execution-mediated path:

1. `list_secret_refs` returns name, environment-variable name, profile, kind,
   and allowed-host metadata—never values.
2. Codex proposes an action containing `paladin://name`.
3. Custodian evaluates the action and destination first.
4. Paladin verifies the grant for requester `codex:<tool-or-session>` and the
   effective authority band.
5. The integration injects the value directly into the authorized child
   process or request transport.
6. Output passes through secret-leak redaction before returning to Codex.
7. Both the governance decision and Paladin resolution are recorded without
   values.

If the integration cannot mediate execution itself, it must not resolve the
secret. Returning plaintext to Codex, even briefly, is not an acceptable
fallback.

## Extraction order after Build Week

1. Commit and push the working Codex checkpoint in the current monorepo.
2. Create `inovinlabs/custodian-codex` and preserve attribution/history using
   a history-preserving split or an explicit provenance note.
3. Publish the shared integration contract from `custodian-kernel`.
4. Make `custodian-codex` depend on released or pinned kernel/Paladin versions.
5. Add conformance CI on Linux and Windows.
6. Release Custodian 0.4.0 only after its independent release checklist passes.
7. Extract Talaria after 0.4.0; keep compatibility imports during transition.
8. Implement Claude, then Antigravity, using the proven contract.

## Non-negotiable security properties

- Fail closed on unknown action kinds, malformed inputs, guard crashes, and
  unavailable enforcement for consequential operations.
- A caller may increase its declared risk but cannot decrease inferred risk.
- An escalation verdict is not execution permission.
- Agents cannot edit policy, audit, approval, vault, plugin, or guard surfaces.
- Arguments and prompts never enter decision receipts.
- Secret values never enter model context, command-line arguments, logs,
  configuration files, Git history, or website code.
- Relative paths resolve against the declared workspace, consistently on
  Linux and Windows.
- Every integration must state honestly what it intercepts. Do not claim to
  govern tools that can bypass its hook or MCP boundary.

## First commands for the next agent

```bash
cd /home/dev/custodian-dev
git status -sb
git branch --show-current
sed -n '1,260p' docs/CODEX_GUARD.md
python scripts/codex-guard-demo.py
python -m pytest -q tests/test_codex_guard.py
```

Expected branch: `feat/codex-guard`. Preserve all uncommitted work. Do not
switch branches, merge, tag, publish, or split repositories until the current
Codex checkpoint has been reviewed and committed intentionally.
