# Custodian Release Path

Versioning rule: plain `0.x.y` only — no alpha/beta labels, no git tags below 1.0
(pre-1.0 framing: the project is recruiting beta testers). Every Stage = one minor
version; everything between stages = patch bumps.

---

## 0.5.0 — Stage 1: Launch

**Theme:** the signed-off governance kernel + Hermes integration ships publicly.

**Scope:**
- Kernel + Paladin + all three harness guards (claude, codex, hermes) in one wheel,
  consolidated under `custodian/guards/` with shim compatibility for pre-0.5.0 import paths.
- Dormant-by-default gate: `custodian guards {enable,disable,status} <name>` — one state
  file (`~/.custodian/guards.json`) every surface reads/writes; flock + unique temp + fsync
  + symlink-safe on both read and write sides; loud corrupt/symlink fallback.
- Install matrix: pip | managed installer (`install-custodian.py`, `--with-codex/claude/hermes`)
  | Hermes plugin (`hermes plugins enable custodian-hermes-guard`).
- Fail-closed credential egress: `allowed_hosts=[]` DENIES egress (no broad default);
  dial-time resolve-and-pin closes the DNS-rebinding gap.
- License: Apache-2.0 (+ NOTICE), uniform with the stack ecosystem.
- Hermes install → enable → verify path: one smooth flow; scratch-profile verification
  artifact published for beta recruitment and the Tek pitch.

**Exit criteria:**
- Wheel `custodian_kernel-0.5.0-py3-none-any.whl` builds with all 9 prepare checks PASS.
- Full suite: 3027+ tests, 0 failures; Claude + Codex sign-off on the final tree.
- A new user completes: install → add secret → grant → guarded run → receipt, without
  editing multiple config files.
- Public: PyPI publish, beta recruitment open.

**Not in this release (documented):** opencode guard (internal only, no public mirror);
iron-proxy/OpenShell integration; approval-presentation UX; audit cross-process serialization.

---

## 0.5.1+ — Patch lane (post-launch, as-needed)

**Theme:** beta-feedback fixes and hardening between stages.

**Scope (candidates, driven by beta feedback):**
- allow_unsandboxed hardening: loud runtime warning now, removal path across 0.5.x.
- Audit cross-process serialization + anti-truncation anchoring (external anchor design).
- UX polish from real users; bugfixes; dependency bumps (tested-version manifest).

**Exit criteria:** each patch lands green (full suite), nothing new on the public surface
that isn't a fix.

---

## 0.6.0 — Stage 2: Egress boundary + approval presentation

**Theme:** the authority layer gains a real network boundary and a human-visible approval UX.

**Scope:**
- iron-proxy seam: Paladin mints short-lived, scoped proxy tokens (L-band, allowed_hosts,
  ttl, run_id, grant_id, nonce); iron-proxy validates and swaps tokens → real secrets at
  egress; dial-time CIDR deny; proxy events correlated to receipts by run_id.
- Egress forcing: HTTP_PROXY/HTTPS_PROXY routing, honestly labeled "configured" vs
  "enforced" until runtime enforcement (Seam C) exists.
- Approval-presentation Phase 1 (branch `feat/approval-presentation-phase1`, 4 files):
  structured ApprovalPresentation store + `custodian-codex present <id>` CLI — the
  foundation for user-friendly approvals.
- One-CLI stack surface: `custodian stack install/status/doctor`, presets (GitHub API,
  Slack, custom HTTPS), optional-component adapters for iron-proxy (marker-gated tests,
  tested-version manifest, fail-closed status).
- Hermes-as-gateway UX: from one Hermes session, install custodian + enable the guard for
  every harness the user owns (claude/codex/hermes) — "install once, govern everything."

**Exit criteria:**
- Agent sees only tokens/grants; real secrets never reach the agent process/env/logs.
- Expired/replayed/wrong-agent/wrong-destination/wrong-method tokens fail.
- `custodian-codex present <id>` shows an approval decision; store is cross-bound HMAC-bound.
- Beta users complete the full flow through the ONE CLI surface.

**Not in this release:** OpenShell runtime (Stage 3); popup/notifier (Phase 2, rides 0.6.x/0.7.0).

---

## 0.7.0 — Stage 3: Runtime isolation

**Theme:** the agent runs inside a real runtime boundary; verification gets the cyberware-informed upgrade.

**Scope:**
- OpenShell/NemoClaw: Hermes launched inside OpenShell via the NemoClaw default driver
  (swappable executor seam; knob-verification test — Landlock `hard_requirement`, forced
  egress — must pass before this is marketed as containment).
- Direct-driver escape hatch (minimal OpenShell launch, no inference stack).
- Status reports `Runtime: enforced` (not configured); startup fails closed on invalid policy.
- cyberware: source-review complete; selective adoption of the verifier/govd sidecar only
  if it strengthens rather than duplicates the decision plane; interoperable
  receipt/provenance boundary defined.
- Approval-presentation Phase 2 (popup/notifier) if not landed in 0.6.x.

**Exit criteria:**
- Direct-socket bypass blocked; non-allowlisted RFC1918 egress blocked; secrets never touch
  agent env/FS; status fails closed on missing/invalid isolation.
- Supported-driver test matrix green; unsupported environments get a clear, non-misleading
  downgrade message.

**Not in this release:** fleet plane (deferred until local authority workflow is validated by users).

---

## Deferred / watch list

- Fleet/multi-agent plane (cyberware's fleet discovery as reference) — only after local
  workflow validation.
- Hermes-as-gateway for EVERY harness the user owns — 0.6.0 UX item, hardware-proofed in 0.7.0.
- Audit external anchor (WORM/remote append-only) — design in 0.5.x, build when warranted.
