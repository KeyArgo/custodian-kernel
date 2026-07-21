# Handover: Custodian modular platform, universal ledger, and installer

**Historical note:** this doc's assignment (item 1 below, the universal
ledger) was completed directly on `main`/`feat/0.5.0-codex`, not on the
separate `feat/0.5.0-modular-platform` worktree/branch described below --
that branch was never created. "0.5.0" as a separate release name is also
no longer the plan: everything, including this ledger work, ships together
as Custodian 0.4.0. Kept for historical record of the original assignment,
not as a current instruction.

You are working alongside another Codex session that owns the OpenAI Build Week
entry on branch `feat/codex-guard`. Do not edit, commit, rebase, merge, or switch
that branch. Do not modify `custodian/codex_guard/`,
`plugins/custodian-codex-guard/`, `scripts/codex-guard-demo.py`,
`tests/test_codex_guard.py`, or `docs/CODEX_GUARD.md`.

Do not tag, publish, or create a GitHub release. Custodian 0.4.0 is still a
release candidate and requires explicit owner approval before release.

## Your assignment (historical -- see note above)

Prepare the 0.4.0 modular-platform foundation:

1. Specify and implement a provider-neutral Custodian action ledger.
2. Specify a modular installation/update system that presents one friendly
   Custodian product while components remain separately packaged.
3. Document the revised repository and dependency architecture.
4. Preserve all 0.4.0 behavior and public imports.

Before designing the ledger, read
`docs/CYBERWARE_SECURITY_COMPARISON.md`. Its P0 ledger requirements are
mandatory acceptance criteria, derived from a source review of Cyberware's
durability and provenance implementation. Do not claim parity or superiority
without passing those criteria.

Work in a separate Git worktree created from `main`, on branch:

```text
feat/0.5.0-modular-platform
```

Suggested setup—adjust the worktree path if it already exists:

```bash
cd /home/dev/custodian-dev
git worktree add /home/dev/custodian-modular -b feat/0.5.0-modular-platform main
cd /home/dev/custodian-modular
```

Before creating the worktree, inspect `git status -sb` and existing worktrees.
Never move or discard another agent's uncommitted files.

## Architecture decision

The user experiences one Custodian platform, but implementation modules have
clear ownership.

### Canonical repositories

- `inovinlabs/custodian-kernel`
  - Authority policy and decisions
  - Human escalation and kill switch
  - Provider-neutral action/transaction ledger
  - Receipt format and verification
  - Adapter contracts and conformance tests
  - Main `custodian setup`, `custodian update`, and `custodian doctor` UX

- `inovinlabs/paladin-vault`
  - Encrypted vault and cryptographic primitives
  - Credential grants, destination restrictions, and value-free vault audit
  - The full agent-facing Paladin product depends on `custodian-kernel` for
    governance before consequential credential resolution
  - Low-level vault maintenance/recovery must remain usable by a human when the
    governance service is unavailable
  - Agent secret resolution fails closed when required governance is unavailable

- `inovinlabs/custodian-stripe`
  - Stripe SDK, PaymentIntent/refund/subscription operations, webhook handling,
    reconciliation, and translation into Custodian ledger events
  - Custodian must not import Stripe or understand Stripe-specific workflows

- `inovinlabs/custodian-skills`
  - Provider-neutral governed skill packs (the future home of suitable content
    currently under `custodian/bundled_skills/`)
  - Explicit manifest roster: a directory is not loadable merely because it
    exists on disk
  - Per-skill hashes, pack roll-up digest, input/output schemas, authority and
    capability declarations, credential-reference names, destination policy,
    tests, provenance, and signatures
  - No kernel, vault, website, or provider-runtime ownership

- `inovinlabs/talaria`
  - Thick Hermes Agent/NemoClaw integration suite

- `inovinlabs/custodian-codex`
  - Codex plugin and MCP integration; owned by the other active session

- `inovinlabs/custodian-claude`
  - Claude Code hooks/plugin

- `inovinlabs/custodian-antigravity`
  - Google Antigravity integration supporting the Gemini/GCP XPRIZE business

Future providers follow the `custodian-<provider>` pattern.

## Skill-pack/cartridge decision

Cyberware separates its engine from `rhCat/skillChip`. Adopt the security
property, not its exact file format or L++/perk abstraction.

Custodian's equivalent is `inovinlabs/custodian-skills`. A pack manifest—not
filesystem discovery—is authoritative. Loading requires all of:

1. the skill is explicitly present in the installed manifest roster;
2. every declared file matches its per-skill digest;
3. the pack roll-up digest matches;
4. the publisher signature verifies against a trusted key;
5. the skill declares action kind, authority band, filesystem/network
   capabilities, credential reference names, and allowed destinations;
6. input/output contracts validate;
7. its self-test and conformance checks passed for the installed artifact;
8. the selected execution assurance tier is available, otherwise execution
   refuses rather than silently weakening confinement.

An undeclared directory, modified script, extra file, missing file, widened
capability, or invalid signature must not load. The installer selects and pins
packs; it does not auto-absorb every discovered skill.

Do not turn provider integrations into skill packs. `custodian-stripe`,
`custodian-codex`, Talaria, Claude, and Antigravity own host SDK/hooks/lifecycle
and remain integration repositories. They may contribute separately packaged
skills through the same manifest contract.

For 0.4.0 compatibility, retain `custodian/bundled_skills/`. Design the signed
pack format and a compatibility adapter in 0.5.x before moving content. Do not
copy Cyberware's offensive skill corpus or implementation; this is an
independent design using Custodian's existing registry and security model.

## Dependency rules

- `custodian-kernel` imports no provider SDK and no integration package.
- `custodian-kernel` does not depend on Paladin.
- The full `paladin-vault` distribution may depend on `custodian-kernel`, but
  keep cryptographic/vault primitives internally isolated from governance code.
- Provider integrations depend on `custodian-kernel`; integrations requiring
  secrets may also depend on `paladin-vault`.
- Skill packs contain declarative capabilities and governed implementations;
  the kernel loads only skills explicitly named and verified by an installed
  pack manifest.
- Integrations never depend on one another.
- Websites—including `getcustodian.xyz`—are consumers, never dependencies.
- No package may contain website-specific credentials, routes, operator
  passwords, deployment configuration, or prompts.

## Universal ledger requirements

Custodian owns a normalized, append-only action ledger. It must support money
and non-money actions without assuming Stripe.

Minimum event fields:

- schema version
- event ID and timestamp
- correlation ID joining the complete lifecycle
- session ID and requester identity
- provider and action name
- lifecycle event (`proposed`, `decided`, `escalated`, `approved`, `denied`,
  `credential_authorized`, `executed`, `failed`, `verified`)
- Custodian verdict and authority band when applicable
- human approver/denier identity when applicable
- amount and currency as optional normalized fields
- estimated/actual cost as optional fields
- external provider ID as optional metadata
- Paladin reference names as optional metadata—never values
- destination host as optional metadata
- previous-record digest/authenticator and receipt reference
- bounded, sanitized provider metadata

Security properties:

- Reject or sanitize raw secret-bearing fields recursively.
- Never store prompts, full command arguments, request bodies, credentials, or
  arbitrary tool output by default.
- Append operations must be crash-safe and concurrency-safe.
- Tampering, reordering, and insertion must be detectable.
- Define truncation/checkpoint behavior honestly; a simple hash chain alone
  does not prove that the tail was not deleted.
- Preserve compatibility with current Custodian audit and Stripe demo records
  through a migration/adapter—not a destructive rewrite.
- Provide query methods by correlation ID, provider, requester, event, verdict,
  time range, and external ID.
- Define a provider-emission protocol so `custodian-stripe` can record Stripe
  events without kernel imports from Stripe.
- Meet every P0 ledger acceptance criterion in
  `docs/CYBERWARE_SECURITY_COMPARISON.md`, including short-write handling,
  torn-tail recovery, one-lock link+append, origin-bound genesis, explicit
  schema migration, and concurrency/crash torture tests.

Begin with a written schema/threat model and tests. Do not replace the current
audit system until compatibility and migration behavior are proven.

## Stripe boundary

Stripe-specific code moves to `custodian-stripe` later. Its events appear in
the universal ledger through normalized fields, for example:

```json
{
  "provider": "stripe",
  "action": "payment_intent.create",
  "event": "executed",
  "amount": "85.00",
  "currency": "USD",
  "external_id": "pi_...",
  "verdict": "autonomous",
  "correlation_id": "..."
}
```

Use decimal/string-safe money representation; do not introduce new binary
floating-point accounting errors. Stripe SDK imports, API calls, webhooks, and
Stripe environment variables must not enter the kernel package.

## Installer requirements

The user should be able to install and update the platform without manually
understanding repositories:

```bash
custodian setup
custodian setup --profile developer
custodian setup --profile msp
custodian setup --profile stripe
custodian setup --with paladin,codex,stripe
custodian setup --dry-run
custodian update
custodian doctor
```

Interactive component choices should eventually include:

- Custodian kernel and universal ledger
- Paladin credential protection
- Stripe integration
- Talaria/Hermes
- Codex Guard
- Claude Guard
- Antigravity Guard
- Local dashboard

Installer security and reliability:

- Linux, Windows, and macOS path/process handling.
- Isolated virtual environment by default.
- No embedded tokens and no secrets in URLs, Git config, process arguments,
  logs, manifests, or repository files.
- Use existing credential helpers or Paladin references for private packages.
- Preserve configuration/data during updates.
- Record an installation manifest with component names, versions, source, and
  compatibility—not secret values.
- Support dry-run, noninteractive, and offline/local-wheel modes.
- Pin/validate compatibility before modifying an installation.
- Stage updates and verify health before switching; provide a recoverable
  rollback path.
- Never silently downgrade security components.
- `custodian doctor` checks imports, versions, ledger integrity, permissions,
  optional provider connectivity, and plugin registration without printing
  secrets.
- Do not use shell-interpolated tokens or `https://TOKEN@...` clone URLs.

For the first change, prefer the provider/component manifest, resolver, dry-run
planner, and tests. Avoid actually installing remote packages until the plan
and rollback model are reviewed.

## Backward compatibility

- Custodian 0.4.0 currently ships `custodian`, `paladin`, and `talaria` together.
- Do not remove or rename those packages, console scripts, or imports in this
  branch.
- Treat modular repositories as a 0.5.x migration.
- Add optional compatibility/deprecation shims before extraction.
- Existing state, audit, policy, vault, dashboard, and demo behavior must pass.
- The main installer may eventually assemble separate distributions, but a
  current editable checkout must continue to work during transition.

## Deliverables for this branch

1. `docs/UNIVERSAL_LEDGER.md`: schema, lifecycle, threat model, provider API,
   migration, and examples.
2. `docs/MODULAR_INSTALLER.md`: profiles, manifest format, planner, update,
   rollback, Windows behavior, private-package auth, and security model.
3. Provider-neutral ledger implementation behind a new API, without replacing
   existing audit paths yet.
4. Unit/adversarial tests for redaction, Decimal money, concurrency, chain
   tampering, malformed provider metadata, and queries.
5. Installer component manifest and dry-run planner with tests. No remote
   installation side effects in the first checkpoint.
6. Architecture-boundary tests preventing Stripe/provider imports in Custodian.
7. A concise checkpoint report listing tests and unresolved migration risks.
8. A completed Cyberware comparison checklist that distinguishes implemented,
   tested, designed-only, and out-of-scope controls.

## Verification

Run focused tests during development, then the full suite. The other branch's
latest known baseline was:

```text
1,975 passed, 1 skipped, 4 deselected
```

Your worktree starts from `main`, so confirm its own baseline rather than
assuming the branch count. Run `git diff --check`, package build, and a Windows-
compatible path review. Do not claim cross-platform verification unless it was
actually run.

## Coordination boundary

The other agent is racing the OpenAI Build Week deadline. Do not ask it to
review intermediate ledger/installer decisions unless genuinely blocked.
Make small, intentional commits only on `feat/0.5.0-modular-platform`. Do not
push, merge, tag, publish packages, create repositories, or modify the website
without explicit owner authorization.
