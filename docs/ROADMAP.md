# Custodian Roadmap — LIVING DOCUMENT

This is the canonical development roadmap for custodian-kernel. It changes as
releases land and decisions are made. Update it at every release and whenever a
plan is adopted or dropped — add an entry to the Changelog at the bottom with the
date and source. Per-version technical specs live in docs/RELEASES.md; this file is
the tracking layer.

## Goals (why we build)

1. Recruit beta testers with a 0.5.0 that is real, installable, and provably working
   (pre-1.0 framing; plain 0.x.y versions; no git tags below 1.0).
2. Tek (Hermes main dev) buy-in: custodian is the completion of the substrate tools
   he promotes — the only authority/receipt layer with a first-party Hermes plugin.
   Lead with the scratch-profile proof, not the pitch.
3. User-friendly: one CLI surface, human concepts, safe defaults, dormant-by-default
   guards, presets. Users see how the guard works; developers get debug internals.
4. No vaporware: every command verified (help + smoke + doc_ref), help/man can never
   drift, CI fails on undocumented or unverified commands.
5. Granular control: per-harness gates, per-harness profiles, deny-always-wins,
   effective-policy provenance.
6. Launch first, platform second. Nothing below gates the 0.5.0 launch.

## Version map (current status)

| Version | Theme | Status | Key content |
|---|---|---|---|
| 0.5.0 | Stage 1 launch | CODE FROZEN, gates pending | kernel + guards + gate + Paladin; Apache-2.0; fail-closed egress; dial-time pin; console/kill/resume |
| 0.5.1+ | Anti-drift patch pack | SCOPED, not built | visibility banner; command-contract sidecar; gates status --harness; identity-write protection; console K warning; allow_unsandboxed hardening; audit serialization |
| 0.6.0 | Stage 2 + capability plane start | SCOPED | iron-proxy seam; approval-presentation Phase 1; presets + per-harness profiles; Hermes-as-gateway; capability manifest + identity status; one-CLI stack surface |
| 0.7.0 | Stage 3 + verifier | SCOPED | OpenShell/OpenClaw/NemoClaw runtime; cyberware-informed verifier/govd; approval Phase 2; Mission Control slices |
| Later | Platform completion | DEFERRED | plugin signing/rollback/quarantine; capability packs (Chronicle/Navigator/Switchboard/Workshop/Airlock/Courier/Skillsmith/Council/Observatory); fleet plane |

## 0.5.0 — Stage 1 launch (code frozen)

Scope: signed-off kernel; 3034 tests; wheel built; manifest all_tests_passed.
Launch gates (operator actions): mirror push -> CI on real tree (Linux/macOS/Windows)
-> Apache-2.0 LICENSE/NOTICE sync -> README canonical Hermes-path sentence ->
scratch-profile Hermes proof -> PyPI publish. NO git tag, NO GitHub release.
Sole freeze exception under discussion: console K persistent-deny warning (else day-zero 0.5.1).

## 0.5.1+ — Anti-drift patch pack

1. IDENTITY-WRITE PROTECTION (public complaint: harnesses rewriting their own
   instructions): write-only denials for home-root MEMORY.md and workspace basenames
   CLAUDE.md / AGENTS.md / .cursorrules / soul.md / MEMORY.md / USER.md. Reads stay
   allowed; operator-only exemption; traversal/symlink bypass impossible; tests.
2. COMMAND-CONTRACT VERIFICATION (anti-vaporware sidecar, Codex design): every console
   script has --help; every subcommand nonempty help + doc_ref + one smoke recipe in an
   isolated temp state dir; markers stateful/network/interactive/destructive; CI fails
   on unverified; help derives from argparse (single source). Read-only
   `custodian-verify --cli-contract` after CI owns it.
3. GUARD-STATE VISIBILITY: activation banner once per session + CLI transition notices;
   CUSTODIAN_VISIBILITY=verbose|debug; debug never shows raw args/secrets/digests.
4. GATES PER-HARNESS STATUS: `custodian gates status --harness <id>` (read-only, over
   the existing gate-policy.json harness model). NO fictitious commands (gates set /
   capabilities / protect --harness do not exist and must not be added without the
   contract tests).
5. CONSOLE K WARNING: K creates a PERSISTENT global deny (not temporary like
   kill/resume) — warn before confirm, name the removal path. (Day-zero unless the
   freeze exception is approved.)
6. allow_unsandboxed hardening (loud warning -> removal); audit cross-process
   serialization + anti-truncation anchor design; beta fixes.

## 0.6.0 — Stage 2 + capability plane start

1. IRON-PROXY SEAM (Stage 2 core): Paladin mints scoped proxy tokens (L-band,
   allowed_hosts, ttl, run_id, grant_id, nonce); iron-proxy validates + swaps at egress;
   egress forcing (configured vs enforced honest labels); receipt correlation by run_id.
   Review constraints: routing enforcement required; RFC1918 defaults from our policy.
2. APPROVAL-PRESENTATION PHASE 1 (branch feat/approval-presentation-phase1 parked):
   ApprovalPresentation store + `custodian-codex present <id>`.
3. PRESETS + PER-HARNESS PROFILES (from operator console design): safe|strict|dev
   presets; per-harness profiles locked-down (Terrarium resident) / builder / reviewer /
   operator; per-harness permissions for fs read/write, network, shell, credentials,
   package install, git mutation, production, governance, outside-workspace; deny
   always wins; grant narrows never widens; effective decisions show source rule +
   receipt; profile selection never silently opens a gate.
4. HERMES-AS-GATEWAY: from one Hermes session install + enable guards for every harness
   the user owns (claude/codex/hermes) — install once, govern everything.
5. CAPABILITY PLANE Phase 0-2 (handoff adopted, re-sequenced): Phase 0 read-only gap
   report FIRST (expected to shrink the 3-5d/2-3w estimates — gate-policy harness model,
   console, receipts, guards already exist); Phase 1 capability manifest + identity
   status (supported/installed/enabled/active); Phase 2 profile compiler with
   effective-policy provenance.
6. ONE-CLI STACK SURFACE: custodian stack install/status/doctor; optional-component
   adapters (iron-proxy binary component; marker-gated tests; tested-version manifest).

## 0.7.0 — Stage 3 + verifier

1. OPENSHELL/OPENCLAW/NEMOCLAW RUNTIME: knob-verification FIRST (does NemoClaw expose
   Landlock hard_requirement + egress forcing? unverified); NemoClaw default driver
   behind swappable executor seam + direct-driver escape hatch; fail-closed startup
   (status says "Runtime: enforced" or refuses); supported-driver test matrix; never
   BestEffort-silent.
2. CYBERWARE: source-review FIRST (govd, value-free wire, fleet plane — README-level
   only so far); interoperable receipt/provenance boundary; selective verifier/govd
   adoption only if it strengthens; get ahead of the "two governance layers" framing.
3. APPROVAL-PRESENTATION PHASE 2 (popup/notifier) if not in 0.6.x.
4. CAPABILITY PLANE Phase 3+ (Mission Control TUI, plugin signing/rollback/quarantine).

## Later / deferred

Fleet plane (after local workflow validated by users); audit external anchor; OpenCode
guard public shipping (hackathon line); capability packs (Chronicle, Navigator,
Switchboard, Workshop, Airlock, Courier, Skillsmith, Council, Observatory).

## Tech ecosystem (engagement map)

- iron-proxy (Apache-2.0, Go): Stage 2 boundary. Fetch-only; never bundle.
- OpenShell (Apache-2.0, Rust, alpha): Stage 3 runtime. Landlock hard_requirement only.
- NemoClaw (Apache-2.0, TS): Stage 3 Hermes/OpenClaw launch driver (default, swappable).
- cyberware (MIT, alpha): control-plane reference; review-first; selective adoption.
- talaria: Hermes-facing product surface (plugin-surface naming decision pending).
- Hermes: the gateway harness; plugin ships in the wheel (entry point).
Anti-hell rules: thin adapters; tested-version manifest; marker-gated tests; one config
surface; fail-closed degradation; no implied endorsement of NVIDIA/ironsh.

## Resolved decisions (2026-08-07, Claude + Codex + operator consensus)

1. K warning: DAY-ZERO 0.5.1 — 0.5.0 stays code-frozen; the warning folds into the
   visibility banner where it belongs. Persistent-deny semantics must be unmistakable.
2. Plugin surface: CUSTODIAN-HERMES-GUARD (first-party, matches the shipped wheel entry
   point); talaria remains the product/suite framing. Hermes-as-gateway (0.6.0)
   consolidates around it — no second integration path.
3. 0.6.0 order: IRON-PROXY SEAM IS THE CRITICAL PATH — approval Phase 1 and
   presets/profiles depend on it. Capability-plane Phase 0 (read-only gap report) may
   run in parallel but never gates the seam.
4. 0.5.1 priority order: IDENTITY-WRITE PROTECTION first (standalone trust gate, public
   harm), then command-contract sidecar, then visibility banner (+K warning), then
   `gates status --harness`, then hardening. Contracts and banner are parallelizable
   (protocol vs UX surfaces).
5. Capability estimates: RE-SCOPE AFTER PHASE 0 — Phase 0 completion is a HARD CHECKPOINT
   before committing 0.7.0 capability scope. 0.7.0 Stage-3 scope stays provisional until
   real sizing data lands.

## What to do when (consolidated sequence)

- THIS WEEK: run the 5 launch gates (mirror push -> CI -> license sync -> README sentence
  -> scratch-proof -> PyPI). Build the authoritative console-command inventory. Patch-lane
  discipline: fixes/hardening only until launch.
- LAUNCH DAY: PyPI publish, NO tag, NO GitHub release. Beta recruitment opens; Tek pitch
  carries the scratch-proof artifact.
- FIRST WEEK POST-LAUNCH (0.5.1): identity-write protection (standalone, no dependents),
  command-contract sidecar in parallel, then visibility banner (+K warning),
  gates status --harness, hardening. CI owns the contract gate before the read-only
  verifier is public.
- 0.6.0: iron-proxy seam FIRST (tokens, egress forcing, receipt correlation stable
  before proxy UX); capability Phase 0 gap report in parallel (never gating); then
  approval Phase 1, presets/per-harness profiles, manifest/identity status, profile
  compiler, one-CLI surface, Hermes-as-gateway.
- 0.7.0+: PROVE containment before claiming it (OpenShell/NemoClaw hard-requirement +
  forced-egress verification, fail-closed swappable driver, test matrix); cyberware
  source-review in parallel (adopt only interoperable pieces); capability Phase 3+
  only after Phase 0 checkpoint. Defer fleet/packs/signing/rollback until local
  workflows validated.

## Open decisions

None — all five decisions resolved 2026-08-07 (see Resolved decisions above). New
decisions get added here and move to Resolved once consensus lands.

## Changelog (how this document evolves)

- 2026-08-07 (initial): created as the living roadmap. Sources: operator console
  conversation (kill/resume, per-harness profiles), capability-plane handoff
  (HANDOFF-CAPABILITY-PLANE-2026-08-07.md, adopted), identity/memory-file research,
  drift-fix plan (Claude+Codex), visibility design (Claude+Codex), stack handover
  (iron-proxy/OpenShell/NemoClaw/cyberware), strategy consensus (launch first).
  Per-version specs: docs/RELEASES.md.
- 2026-08-07 (update): open decisions RESOLVED by Claude+Codex+operator consensus
  (K warning day-zero; plugin surface = custodian-hermes-guard; iron-proxy seam is the
  0.6.0 critical path with Phase 0 parallel; 0.5.1 order identity -> contracts -> banner
  -> gates status -> hardening; capability estimates re-scoped after Phase 0 = hard
  checkpoint). Consolidated what-to-do-when sequence added.
