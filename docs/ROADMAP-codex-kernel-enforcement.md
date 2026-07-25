# Roadmap: Make Codex 100% kernel-enforced, maximize Paladin, then release 0.1.2

Status: **APPROVED TO PLAN — awaiting go on Phase 0+1.** Created 2026-07-23.
Owner: this AI session (Talaria/codex-guard side). Do not commit/push/tag/publish
without explicit operator permission (see Phase 3 hard stop).

## Goal & ordering (operator's stated priorities, in order)
1. **Codex cannot act except through the kernel** — non-bypassable, not advisory.
2. **Maximize the Paladin connection** — Codex checks Paladin *first* for any
   password it doesn't hold, whenever Paladin is configured.
3. **Only then, and only with explicit operator permission**, cut `0.1.2`:
   commit -> push -> tag -> PyPI.

## Context: why this exists
codex-guard today enforces via an **opt-in MCP tool** (`guard_action`) that the
model must *choose* to call (SKILL.md advises it). A jailbroken / prompt-injected
/ uncooperative model bypasses it entirely. Claude Code's equivalent guard
(`custodian/claude_guard/`, built 2026-07-23) instead runs in a **PreToolUse
hook** the harness enforces deterministically — non-bypassable. Codex CLI has
since gained the same lifecycle-hook mechanism (blocking `PreToolUse`, exit 2 /
`permissionDecision:"deny"`), plus `execpolicy` and `allow_managed_hooks_only`.
So Codex can now be made to comply the same way. This roadmap retrofits
codex-guard from advisory MCP to enforced hook, reusing the identical shared core
`custodian.codex_guard.mcp_server.evaluate_guard_action(harness="codex")`.

---

## Phase 0 — De-risk the hook contract (no code)
The `PreToolUse` contract so far came from OpenAI's docs summary
(`learn.chatgpt.com/docs/hooks`), not a live binary. Before building:
- Confirm against the installed `codex` that `[[hooks.PreToolUse]]` exists, its
  exact matcher syntax, the deny JSON shape, and which tools it intercepts
  (`shell`/`Bash`, `apply_patch`, MCP, function tools).
- Confirm `allow_managed_hooks_only` lives in `requirements.toml` and what layer
  it locks.
- **Gate:** if the installed Codex lacks a blocking `PreToolUse`, fall back to
  `execpolicy` + OS sandbox for tier-1 enforcement and flag before proceeding.

## Phase 1 — Non-bypassable enforcement ("100% through the kernel")
1. **`custodian/codex_guard/hook.py`** — PreToolUse hook reusing
   `evaluate_guard_action(harness="codex")`, built on the proven fail-closed
   pattern in `custodian/claude_guard/hook.py` (every abnormal path -> explicit
   `deny`; never silent exit-0). Map `denied->deny`,
   `escalation_required->ask`, `autonomous/approved->allow`.
2. **Extend `custodian-codex setup`** to install the `[[hooks.PreToolUse]]` block
   into `~/.codex/config.toml` — interpreter-pinned, idempotent, refuses to
   clobber invalid TOML (same safety as the claude installer in
   `custodian/claude_guard/cli.py`). Matcher covers Bash/shell/`apply_patch`/MCP/
   function tools.
3. **Managed-hook lock:** set `allow_managed_hooks_only = true` in
   `requirements.toml` so a user/project/session config — or a malicious repo's
   `.codex` — cannot strip the guard. This turns "installed" into "100% required."
4. **Keep the MCP server** for `verify_receipts`/`list_receipts` visibility, but
   enforcement no longer depends on the model calling `guard_action`.
5. **`custodian-codex doctor`** gains checks: hook installed, interpreter matches,
   managed-lock present -> fail loudly if any missing.
6. **Tests** (mirror `tests/test_claude_guard.py`): decision matrix, fail-closed
   matrix, installer merge safety, and a regression proving enforcement holds
   **with the MCP server absent**.
7. **Docs:** update `SKILL.md`/README from "call `guard_action` before acting"
   (advisory) to "the harness enforces the guard" (mandatory).

Note: the codex-guard newline destructive-bypass fix
(`custodian/codex_guard/guard.py` `_SHELL_RULES`, `echo hi\nrm -rf ~` was
classified autonomous; fixed with `\n\r` in the separator class + `re.M`) is
already in the working tree and rides along in this phase's commit.

## Phase 2 — Maximize Paladin: Codex checks Paladin first for passwords
Built on `paladin/git_credential.py` + `Broker._resolve(SecretRef, requester,
band)`, which already fails gracefully when no grant exists.
1. **Auto-wire the git credential helper** during `custodian-codex setup` when a
   vault exists — Codex git ops resolve tokens from the vault, never prompt,
   never hardcode.
2. **Credential resolution order** in the guard/hook path: when an action is
   classified `CREDENTIAL` (or needs a secret), resolve `paladin://ref` via the
   Broker **first** (if configured & granted) -> else **escalate to human**.
   Never let Codex fabricate, prompt, or inline a raw secret that skips the vault.
3. **Graceful degradation:** if Paladin isn't configured or the vault is locked,
   fail closed for the action but don't break unrelated ops (mirrors
   `git_credential.py`'s exit-0 fallthrough).
4. **`doctor` verifies Paladin is "maximized":** vault reachable, git helper
   wired, expected grants present.
5. **Tests:** credential action with a configured paladin ref -> resolved;
   without -> escalate; vault locked -> fail closed.

## Phase 3 — Release 0.1.2 — HARD STOP, PERMISSION REQUIRED
Nothing here runs until the operator says go. When approved:
1. **Reconcile versioning** — this dev monorepo builds `custodian-kernel 0.4.0`;
   the published package is `custodian-codex-guard 0.1.x`. Confirm `0.1.2`
   targets that package/repo and the tag scheme.
2. CHANGELOG entry; full suite green; build + clean-env install verify.
3. Commit on a branch (not `main`) -> push to the `custodian-codex-guard` GitHub
   repo -> tag `v0.1.2` -> publish to PyPI.

---

## Decisions needed before Phase 3 (not blocking Phases 0-2)
- **Version target:** is `0.1.2` the `custodian-codex-guard` package? Does the
  `custodian-kernel` monorepo version move too?
- **Bundle scope:** ship the already-built claude-guard in this same `0.1.2`, or
  hold it for a separate release?
- **`allow_managed_hooks_only`:** enabling it to lock the guard also makes Codex
  ignore the operator's *personal* user/project hooks. Enable, or document as
  opt-in only?
- **Matcher scope:** govern **all** Codex tools (catch-all, unknown/MCP ->
  escalate) vs. just the dangerous set.

## Phase 0 RESULT — verified Codex PreToolUse contract (codex-cli 0.144.6, from the binary)
- Hooks exist and PreToolUse is BLOCKING ("Command blocked by PreToolUse hook:").
- Config: `~/.codex/config.toml`, `[[hooks.PreToolUse]]` with `matcher`, then
  `[[hooks.PreToolUse.hooks]]` with `type="command"`, `command`, opt `timeout`/
  `statusMessage`/`async`. Layered config: user/project/session + managed
  (managed_config.toml) + requirements.toml (holds `allow_managed_hooks_only`).
- Event names internally snake_case (pre_tool_use, permission_request, ...);
  config/JSON use PascalCase; `hookEventName` const "PreToolUse".
- INPUT fields: cwd, hook_event_name, session_id, tool_name, tool_input (any),
  tool_use_id, tool_response, transcript_path, turn_id, permission_mode-like enum
  [acceptEdits, plan, dontAsk, bypassPermissions,...]. (cwd, hook_event_name req.)
- OUTPUT to BLOCK: {"hookSpecificOutput":{"hookEventName":"PreToolUse",
  "permissionDecision":"deny","permissionDecisionReason":"<NON-EMPTY, required>"}}.
  Exit 2 + stderr also blocks.
- **CRITICAL DIFFERENCE FROM CLAUDE:** runtime REJECTS `permissionDecision:allow`
  and `permissionDecision:ask` (literal errors "unsupported permissionDecision:
  ask/allow"), and `decision:approve`. So PreToolUse = DENY or DEFER(empty) only;
  it cannot force-allow or ask. Codex hook needs its own emitter (do NOT reuse
  claude_guard's allow/ask output).
- Mapping chosen: denied->deny; escalation_required->deny WITH the approve
  instructions in the (required) reason [Codex has no native ask, so the existing
  single-use `custodian-codex approve ID --digest` flow IS the ask]; autonomous/
  approved->empty output (defer to Codex normal flow; never widens). Because a
  PreToolUse deny precedes Codex's own approval decision, it blocks even under
  approval_policy=never / trust_level=trusted — that is the "100% through kernel"
  guarantee.
- Self-protection already present: guard classifies writes to `.codex`/config as
  governance->escalation (guard.py _SENSITIVE_WRITE_PATH). Phase 1 also adds
  `~/.codex` to the default deny paths so bash redirects into it are fenced too.
- Escalation re-run needs digest-based approval lookup (hook has no approval_id
  channel): add ApprovalStore.find_approved + mcp_server auto-consume-by-digest.

## Progress log
- 2026-07-23: **Phase 0 DONE** — Codex hook contract verified from binary (above).
- 2026-07-23: **Phase 1 DONE** — mandatory enforcement shipped in working tree
  (uncommitted). Delivered:
  - `custodian/codex_guard/hook.py` — Codex PreToolUse hook (deny-or-defer;
    Codex-correct emitter; fail-closed; classify_tool for hook path).
  - `custodian/codex_guard/hook_install.py` — delimited, tomllib-validated,
    idempotent, interpreter-pinned install/uninstall/status for ~/.codex/config.toml;
    refuses to clobber invalid TOML.
  - `custodian-codex setup` now installs the hook (+ warns/fails if it can't);
    `doctor` fails if the enforcement hook is missing/stale; new `hook-uninstall`.
  - `ApprovalStore.find_approved` + mcp_server auto-consume-by-digest → the
    escalation→out-of-band-approve→identical-rerun→single-use flow works with NO
    approval_id channel (hook only sees the tool call). Verified end-to-end.
  - Self-protection: added `~/.codex`/`~/.claude` to default deny paths so bash
    redirects into the guard config are fenced (apply_patch already was).
  - Entry point `custodian-codex-guard-hook`; SKILL.md + README updated to
    "mandatory, not advisory".
  - Tests: `tests/test_codex_hook.py` (32). Full suite: 2672 passed, 1 skipped.
  - STILL OPEN in Phase 1 (deferred, needs live-codex verification): managed lock
    `allow_managed_hooks_only=true` in requirements.toml so a user/project/session
    config can't strip the hook. Guard already denies writes to ~/.codex, so the
    model can't disable it; the managed lock is belt-and-suspenders + admin policy.
    Also: a live `codex exec` smoke test of the installed hook before release.
- 2026-07-23: **LIVE SMOKE TEST — critical finding (Codex hook trust).** Ran
  `codex exec` (0.144.6) against the installed user-level hook. The hook did NOT
  fire (no receipt) and the command ran under Codex's own sandbox. Root cause,
  confirmed from the binary: Codex hooks have trust states **Managed / Trusted /
  Untrusted**. A user-level `~/.codex/config.toml` hook starts **Untrusted** and
  is **silently skipped in `exec`** until the operator approves it once in the
  TUI ("Hooks need review"); trust is persisted as a content hash
  (`trusted_hash`/`current_hash`) in `state_5.sqlite`, NOT a config field, so it
  cannot be script-injected. **"Managed hooks are always on"** — a hook in
  `/etc/codex/managed_config.toml` is auto-trusted, runs in exec, and with
  `allow_managed_hooks_only=true` in `/etc/codex/requirements.toml` cannot be
  stripped. So the true "100% required, always-on" guarantee needs EITHER:
    (a) user-level hook + a one-time TUI trust approval (per operator, per hook
        content change), OR
    (b) a **managed** install under /etc/codex (needs root; env override
        CUSTODIAN_CODEX_MANAGED_DIR for testing) — no trust prompt, unstrippable.
  This machine has no passwordless sudo and no /etc/codex, so the live block
  could not be demonstrated here; operator must either approve trust once or
  provide the managed install.
  IMPLICATION: the earlier "blocks even under approval_policy=never" claim is true
  ONLY once the hook is trusted/managed. Untrusted user hooks are skipped, full stop.
- 2026-07-23: Implementing per operator decisions: managed lock = OPT-IN flag
  (`custodian-codex setup --managed-lock`), not default; doctor now surfaces
  trust state guidance. THEN operator completes the live proof.
- 2026-07-23: **Managed (always-on) enforcement + escape hatch — operator chose B,
  "works for everyone", with a deliberate disable.** Implemented:
  - `hook_install.install_managed()` — writes the guard hook to Codex's managed
    layer (always-on, auto-trusted, no TUI prompt) + `allow_managed_hooks_only=
    true` so user/project/session config can't strip it. `custodian-codex setup
    --managed-lock` (opt-in per earlier decision).
  - `managed_dir()` now platform-aware: /etc/codex (POSIX), %PROGRAMDATA%\\Codex
    (Windows), `CUSTODIAN_CODEX_MANAGED_DIR` override (tests / MDM / non-root
    operator-owned managed dir). `elevation_hint()` prints sudo vs Admin per-OS.
  - **Escape hatch:** `custodian-codex hook-uninstall --managed` removes the
    managed hook AND the lock so Codex runs normally again if the guard
    misbehaves. Deliberately privileged (root/admin-owned managed dir), so only
    the operator — never the model or a repo config — can disable enforcement.
    Preserves any unrelated managed config.
  - doctor distinguishes MANAGED always-on (locked/not) vs user-level (needs
    one-time trust) vs not-installed.
  - Tests: 78 in test_codex_hook.py (managed install/uninstall/idempotency/
    platform paths/escape hatch). Full guard suite 231 passed.
  - Demonstrated root-free via the override: install→doctor(MANAGED locked)→
    hook-uninstall --managed→doctor(gone). Verified.
  - TRUST MODEL SATISFIED: model/repo cannot disable (managed dir is admin-owned
    + guard denies ~/.codex writes); operator with root can always disable.
- STILL PENDING: the live `codex exec` block demonstration needs a real managed
  dir (root) or a one-time user-level TUI trust — operator action on a box with
  sudo / a writable managed dir. Contract + logic fully proven in tests.
- 2026-07-23: **doctor now has a 3-state enforcement report (approved change).**
  Codex's hook trust state is a content hash in ~/.codex/state_5.sqlite that we
  CANNOT read, so a user-level install is unverifiable from our side. doctor now:
  MANAGED -> OK (verifiably always-on); user-level installed -> **WARN** with
  "INSTALLED BUT NOT VERIFIABLE" + a loud summary banner (never a bare OK);
  missing/stale -> FAIL (exit 1). WARN keeps exit 0 (install isn't broken) but
  the banner makes the unverified state unmissable. Pinned by
  TestDoctorEnforcementState (3 tests). Rationale: a soft OK could let an
  operator OR a judge believe they're protected when enforcement is silently
  inert. Full guard suite: 243 passed.
- 2026-07-23: **CORRECTION to an earlier overclaim in this session.** I had said
  "judges can and DID use it." We have NO evidence any judge executed the guard:
  no telemetry/callback exists, the only receipts are our own local demo runs,
  and per HANDOVER-POST-SUBMIT.md line 191 `pip install custodian-codex-guard`
  did not work at submission (not on PyPI, unsatisfiable deps) -- a judge who
  followed the documented quickstart would have hit a broken install before any
  guard behavior. Build Week judging is most plausibly video + repo review, not
  live execution. Accurate statement: the SUBMITTED artifact (MCP + govern-codex
  skill) is usable interactively but ADVISORY (model must choose to call
  guard_action); it is not proof of non-bypassable enforcement. That gap is the
  entire reason for the hook work in this roadmap.
- NEXT: finish live proof (operator, on a root-capable box), then Phase 2 (Paladin). claude-guard already built & tested (37 tests);
  codex-guard newline bypass fixed (in working tree, uncommitted). Phases 0-3
  not yet started; awaiting go on Phase 0+1.

## Phase 2 RESULT — Paladin wired to codex-guard (2026-07-23)
Done and green (full custodian-dev suite: **2597 passed, 1 skipped**; Talaria's
own suite: **71 passed**, incl. its Paladin egress).

- **Package boundary respected — the key constraint.** `custodian/` (codex-guard
  included) must NEVER import `paladin` (`tests/test_architecture_boundaries.py`
  enforces it; the kernel stays brand-neutral). So `custodian/codex_guard/
  paladin_bridge.py` reaches Paladin the way the guard reaches `git`/`codex`: as
  an **external CLI** (`paladin` on PATH, via subprocess) and a **file on disk**
  (the vault), never as a Python import. The `paladin://` ref regex + the vault-
  path resolution are re-implemented locally (same pattern secret_leak_guard.py
  already uses). First draft imported paladin and correctly tripped the boundary
  test; rewritten. Do NOT "fix" a future boundary failure by importlib-dodging
  the check — that would make the brand-neutrality promise silently false.
- **Git credential helper (transparent path).** `custodian-codex paladin-git
  <host> <ref>` shells out to `paladin git-setup`, so Codex `git push`/`fetch`
  resolves the token from the encrypted vault at request time — never in git
  config, a URL, argv, or Codex's context. This IS "Codex checks Paladin first
  for a password it doesn't hold," fully transparent to the model.
- **Credential guidance (policy path).** On a credential-class escalation — OR
  any escalation whose args already carry a `paladin://` ref (e.g. a `curl` that
  classifies as `network` but needs a token) — the escalation reason gains a
  vault-egress steer (name the ref if present; else the generic `paladin add` /
  `paladin exec` path). Inlining a RAW secret was already DENIED upstream by
  SecretLeakGuard; this adds the positive "here's the vault path" half. Value-
  free and best-effort: no vault / no paladin => "" => unchanged escalation.
- **Never unlocks on the hot path.** "Is a vault configured?" is a pure file-
  exists check (honors PALADIN_HOME); the passphrase is never touched by the
  guard. Resolution happens at egress inside Paladin (git helper / `paladin
  exec`), never in a PreToolUse hook that fires on every tool call.
- **doctor Paladin section.** Reports available / vault-configured / git-helper-
  wired as WARN|OK (never FAIL — Paladin is optional). A Paladin-only WARN gets
  its own summary banner distinct from the enforcement banner, so an unwired
  credential path is never misreported as inert enforcement.
- **Tests:** `tests/test_codex_paladin_bridge.py` (17): vault detect w/o unlock,
  value-free ref extraction, guidance messaging, guard-integration (credential /
  network+ref / plain-destructive-no-steer / no-vault-graceful), doctor WARN/OK,
  paladin-git graceful failure.
- **Three-way state (verified):** paladin (neutral broker) <- talaria (Hermes
  egress, 71 tests) and <- codex-guard (Codex, this phase) are PARALLEL
  integration layers on the same neutral kernel + same `paladin://` convention +
  same vault. No direct talaria<->codex-guard coupling (by design). A secret
  added once is usable by both Hermes and Codex, governed identically.
- STILL PENDING: live `codex exec` proof (operator/root box); interpreter-
  stability decision for managed hooks; Phase 3 release (HARD STOP, needs go).

## Security mutation gate — the guard graded against itself (2026-07-23)
Prompted by the operator asking whether to adopt cyberware's "we dogfood our own
governance / gates are mutation-tested / caught once -> permanent gate" pitch.
Decision: adopt the *substance* in Custodian's OWN true voice, and EARN the
mutation-testing claim rather than borrow cyberware's model-checking/L++ wording
(which Custodian does not have — asserting it would repeat the "judges DID use
it" overclaim we corrected earlier this session). So we built the real thing.

`tests/test_guard_mutation_gate.py` (12 checks): for each security-critical
decision in the guard, flip exactly one line in a mutated in-process copy and
prove a concrete adversarial input catches it. Covers: destructive-command
classification (incl. the newline-bypass we fixed), overstate-never-understate
risk promotion, the escalation gate, unknown-kind fail-closed, bogus-workspace
fail-closed, and BOTH hooks' verdict maps (codex deny/defer + missing-field
fail-closed; claude deny/ask/allow + missing-field fail-closed). Each mutation
first asserts its target line exists *uniquely* — so a refactor makes the gate
FAIL loudly rather than silently rot into a no-op (the gate holds itself to the
same "can never silently return" bar it enforces).

Real finding from building it: the naive newline probe (`echo hi\nrm`) SURVIVED,
because the fix added BOTH `\n\r` to the separator class AND `re.M` — overlapping
defenses, either catches a line-start `rm`. The gate forced the honest isolating
probe: an INDENTED destructive command after a newline (`echo hi\n  rm ...`),
which only the character-class edit breaks. i.e. the gate found a real coverage
nuance the existing regression test missed.

Honest scope: this is a *targeted* gate over enforcement invariants (fast,
deterministic, no external dep, runs every build), NOT exhaustive mutation
coverage. `mutmut` is NOT installed here and was deliberately NOT faked into CI;
exhaustive mutation runs scoped to `custodian/*_guard/` are documented as an
out-of-band option only. Wired as its own named CI step ("Security mutation gate
(the guard graded against itself)") and `make mutation-gate`, so it reads as a
distinct line in the build log. Full suite after adding it: green (see run).

What Custodian can now TRUTHFULLY say (vs cyberware): "every security decision in
the guard is mutation-tested; a caught bug-class becomes a standing gate" — and
LINK the files (`test_guard_bypass_regressions.py`, `test_architecture_boundaries.py`,
`test_guard_mutation_gate.py`). We SHOW it; cyberware asserts it. Do NOT claim
model-checking / L++ blueprints — Custodian has neither.

## Self-hardening gate corpus — "the code improves itself" (2026-07-23)
Operator's follow-up: not a marketing card — build the actual "improves itself"
capability cyberware claims. Clarified first what that claim really is: NOT code
that autonomously rewrites its own logic, but a **ratcheting, self-grading
build** — "caught once -> permanent gate; can never silently return." So we
built the honest mechanism: the guard's *coverage* grows itself and can only get
stricter, while the decision logic stays human-authored (a security boundary
must not silently self-edit — and cyberware doesn't claim that either).

Pieces:
- `custodian/codex_guard/corpus.py` — the ratchet. A gate corpus is append-only
  concrete adversarial inputs, each frozen at a FLOOR verdict. Replay asserts the
  guard is at least that strict: verdicts may tighten (escalate->deny ok), never
  weaken (escalate->autonomous FAILS). Monotonic-safe, so a closed hole can't
  silently reopen. Brand-neutral (no paladin import).
- `scripts/harden_guard.py` — the engine. GENERATES adversarial inputs across
  families (destructive w/ separator+whitespace+casing obfuscation, network/
  exfil, production/deploy, credential, self-tamper, argv-list form, mapped
  destructive tool names, bogus-workspace). Caught -> freeze as a new permanent
  gate (`--freeze`); ESCAPED -> print loudly + exit 1 (never auto-freeze a bug
  as correct; a human fixes the classifier, then it freezes on the next run).
- `tests/corpus/guard_gates.jsonl` — 67 frozen gates (seeded by the first hunt).
- `tests/test_guard_gate_corpus.py` — the standing gate: replays the corpus
  (ratchet) AND re-runs the generator (fresh hunt) every build = "building is
  running." Wired into CI + `make harden` / `make mutation-gate`.

WHY GENERATE, NOT HARVEST: the guard's receipts are deliberately VALUE-FREE — the
actual command string never enters a receipt (verified in receipts.py: it stores
verdict/action_kind/tool, never `arguments`). So production denials can't be
replayed; the engine must manufacture its own concrete attacks, which it can
freeze exactly. Correct security posture, real constraint, documented.

REAL BUG THE ENGINE FOUND ON ITS FIRST RUN: `echo $STRIPE_SECRET_KEY` (and
`printenv STRIPE_SECRET_KEY`) classified **autonomous** — exposing a secret-named
env var to stdout dumps the value into the agent's transcript, the exact leak
Paladin exists to prevent, running UNGUARDED. Fixed in guard.py with a tightly-
scoped credential-exposure rule (`_SECRET_VAR_NAME` + exposure verbs echo/printf/
print/printenv/env), escalate not deny. Verified precise: catches
$STRIPE_SECRET_KEY / ${GITHUB_TOKEN} / $DB_PASSWORD / $AWS_SECRET_ACCESS_KEY,
leaves $HOME/$PATH/$USER/$MONKEY/$KEYBOARD and presence-checks
(`[ -n "$API_KEY" ]`, no exposure verb) AUTONOMOUS. Pinned three ways: mutation
gate entry, corpus gate, and the fresh hunt. This is the loop working exactly as
designed — engine hunts, human fixes logic, gate becomes permanent.

HONEST SCOPE: coverage self-improves; logic does not self-rewrite. Targeted
attack families, not exhaustive. `mutmut` still not installed / not faked.
Residual known gaps left un-fixed on purpose (scope discipline): bare `env`/
`printenv` with no arg (dumps all vars) not yet caught; noted, not claimed.
