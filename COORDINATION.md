# Custodian Capability Kernel — Live Coordination Ledger

**Plan:** `../../Vaults/handovers/custodian-capability-kernel-execution-plan.md` (v1.1.0)
**Contract version:** _(frozen at P0 gate — not yet frozen)_
**Steward:** _(assigned to G2's owner at gate freeze)_
**Status:** BREADTH-LANE ACTIVE — Tier-B breadth lanes dispatched, pre-gate spec work. Contract not yet frozen by P0 gate + Daniel sign-off; all workers code against plan-spec interfaces. Review-bound: Tier-A/S neighbor review required before A12 merges.

> Rules (see plan §2): append your own rows only; never rewrite another agent's row. Claim BEFORE you branch. Heartbeat at the start of each session. If your owned paths overlap an active claim, STOP and escalate to the steward — that's a matrix error, not a merge to resolve.

---

## Claims

| agent | workstream | owned_paths | branch | status | last_heartbeat |
|-------|-----------|-------------|--------|--------|----------------|
| a3 | money-demo | demos/money/*, scripts/demo-money.sh | feat/a3-money-demo | active | 2026-07-05T19:00Z |
| a5 | secret-silo | custodian/broker/silo/*, custodian/broker/secret_pointer.py | feat/a5-secret-silo | active | 2026-07-05T19:00Z |
| a6 | credential-demo | demos/credential/*, scripts/demo-credential.sh | feat/a6-credential-demo | active | 2026-07-05T19:00Z |
| a9 | file-capabilities | custodian/broker/capabilities/file_read.py, .../file_write.py | feat/a9-file-caps | active | 2026-07-05T19:00Z |
| a10 | session/document | custodian/broker/capabilities/session.py, .../document.py | feat/a10-session-doc | active | 2026-07-05T19:00Z |
| a11 | dashboard/govd-lite | dashboard/**, custodian/broker/control_api.py | feat/a11-dashboard | active | 2026-07-05T19:00Z |
| docs | workstream sub-specs | docs/workstreams/a3.md, a5.md, a6.md, a9.md, a10.md, a11.md | feat/docs-workstreams | active | 2026-07-05T19:00Z |
| a13 | privacy-adapter | integrations/sillytavern/**, docs/workstreams/a13.md | feat/a13-sillytavern-adapter | parked (private, never-merge) | 2026-07-05T21:00Z |
| a13-st-design | privacy-adapter-design | integrations/sillytavern/DESIGN.md | feat/a13-sillytavern-adapter | parked (private, never-merge) | 2026-07-05T21:00Z |
| a5-silo-tests | silo-unit-tests | tests/unit/silo/** | feat/a5-silo-tests | active | 2026-07-05T19:22Z |
| video-shot-script | video-shot-script | docs/video/shot-script.md | feat/video-shot-script | active | 2026-07-05T19:22Z |
| positioning | positioning | docs/positioning/** | feat/positioning | active | 2026-07-05T19:22Z |
| warden | credential-broker (standalone) + adapter-framework + talaria-suite | warden/**, custodian/adapters/**, talaria/**, skills/custodian-meta/**, tests/test_warden*.py, tests/test_adapters*.py, tests/test_talaria*.py, docs/WARDEN.md, docs/ADAPTERS.md, docs/TALARIA.md, docs/SECURITY-HARDENING.md | feat/warden-adapters-hermes (merged to main) | active | 2026-07-14T14:30Z |

---

## Interface Requests
_(requesting agent → target owner: the interface you need, and why. Owner replies here with the resolved signature.)_

- [OPEN] a13→a5: need `Silo.resolve(secret_ref)` for persona-card embedded secrets. (a13 reads, never writes silo/*.)
- [OPEN] a13→a10: need the session/document capability shape to wrap private session data (persona cards, chat logs) as a governed resource without exfiltration.
- [OPEN] a13→a9: need file_read/file_write capability for persona-card + log files under a silo grant.

---

## Contract Amendments
_(post-freeze only. Propose exact field/shape change + reason + affected agents. Steward ratifies, bumps contract version, records in plan §12.)_

- (none yet)

---

## Plan Amendments
_(propose changes to the master plan here. Steward ratifies, edits the section, bumps plan version, appends plan §12 changelog.)_

- (none yet)

---

## Blockers
_(anything stopping a claimed workstream. Owner + what's blocked + what's needed.)_

- None currently. All agents operating on spec-driven worktrees against plan interfaces. P0 gate (G1/G2) not yet complete — no merge to main until gate passes + Daniel sign-off.

## Pre-gate batch (2026-07-05, verified)
4 zero-collision pre-gate branches on gitea, verified by inspection (Hermes report accurate this time):
- feat/a13-sillytavern-adapter @9a86d80 — integrations/sillytavern/DESIGN.md (907 lines, persona-session data-model → Contract mapping; unblocks the privacy adapter)
- feat/a5-silo-tests @37cb579 — tests/unit/silo/** (5 files; off-track worker copy stripped -82, real tests added; silo imports clean)
- feat/video-shot-script @b705365 — docs/video/shot-script.md (12 shots, REAL working features only)
- feat/positioning @d56e55f — docs/positioning/{sovereignty,cyberware-comparison}.md
main untouched, gate still blocks merge.

## Push status (2026-07-05)
All 7 Tier-B feat branches committed + pushed to `gitea` remote (LAN). Straggler commits added by review pass (a6/a9/a10/a11 had uncommitted/staged work Hermes reported as done — corrected). `main` untouched; merge remains gate-blocked (§2.9).
- feat/a3-money-demo @60fbcca · feat/a5-secret-silo @80d79e5 · feat/a6-credential-demo @9aee80c · feat/a9-file-caps @ab26fb8 · feat/a10-session-doc @0213ac9 · feat/a11-dashboard @540d451 · feat/docs-workstreams @f034dbf

New pre-gate breadth dispatch (4 workers, all pushed):
- feat/a13-sillytavern-adapter @9a86d80 · integrations/sillytavern/DESIGN.md (persona-session data-model research)
- feat/a5-silo-tests @37cb579 · tests/unit/silo/** (5 test files, 1173 insertions — Silo/Pointer/Policy/Security/Integration)
- feat/video-shot-script @b705365 · docs/video/shot-script.md (narration for real features, 8-12 shots)
- feat/positioning @d56e55f · docs/positioning/sovereignty.md + docs/positioning/cyberware-comparison.md

## Warden + adapters + hermes-bridge dispatch (2026-07-14)
`feat/warden-adapters-hermes` — three-part capability build, all tests green (1527 passed, +80 new):
- **Warden** (`warden/**`): standalone AES-256-GCM credential broker — encrypted vault, scrypt KDF, password-manager CLI (`warden` entry point), env profiles, `warden://` SecretRefs, deny-by-default grants, hash-chained HMAC audit, egress-only injection (agent never sees values). Optional receipt co-signing.
- **Adapters** (`custodian/adapters/**`): guard-adapter framework (pre/post/handle hooks) + 9 built-ins (spend-sentinel, prompt-injection-guard, secret-leak-guard, kernel-self-protection, pii-redactor, context-anchor, repetition-breaker, tool-confabulation-guard, scope-fence); registry with hash-pinned local installs; `custodian adapters` CLI.
- **Hermes bridge** (`integrations/hermes/**`): one governed invoke() surface (adapters → kernel → Warden egress → post-scan), SessionCapsule for context-loss re-anchoring, session-policy YAML for granular tool/file/host/spend control, soul compiler, introspection meta-skills, NemoClaw governed egress.
- Docs: WARDEN.md, ADAPTERS.md, HERMES-BRIDGE.md, SECURITY-HARDENING.md, positioning/cyberware-head-to-head.md.
- _2026-07-14 update: the Hermes bridge was promoted to a top-level suite named **Talaria** (`integrations/hermes/**` → `talaria/**`, HERMES-BRIDGE.md → TALARIA.md, test_hermes_bridge → test_talaria) and gained a unified `talaria` CLI (vault/adapters/session/init). Broker remains `warden` pending its final name._
