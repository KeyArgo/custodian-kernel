# Changelog

All notable changes to custodian-kernel are recorded here. Dates are UTC.

## [0.4.3] — 2026-08-02

### Vendor-neutral payment processing

- Added `custodian.processors.base.PaymentProcessor`, a vendor-neutral
  interface (`charge`/`refund`/`payout`/`balance`) so a payment vendor
  integration no longer needs to be bundled with the kernel to work with it.
  Ships with `ManualLedgerProcessor`, an in-memory reference implementation
  that needs no real vendor.
- Added `custodian.authority.ledger`: the crash-safe atomic-write, file-lock,
  and append-log primitives used by the bundled Stripe skill, now available
  to any processor implementation.
- The tool registry and `custodian setup` now discover externally-registered
  skills and setup components/profiles via `importlib.metadata` entry points
  (`custodian.skills`, `custodian.setup_components`, `custodian.setup_profiles`),
  so a separately-installed package (e.g. a Stripe or other payment-processor
  adapter) can register itself with zero kernel code changes. Built-in names
  always win on a collision; a broken third-party entry point is skipped, not
  raised.
- `custodian/` is now mechanically forbidden from importing any payment
  vendor SDK directly (enforced by `tests/test_architecture_boundaries.py`),
  keeping the kernel itself vendor-neutral going forward.

## [0.4.1] — 2026-07-27

### Installation and lifecycle recovery

- Custodian Kernel 0.4.1 supports Linux and macOS on Python 3.11 through 3.13.
  Windows remains in development CI and is planned as a supported platform for
  0.4.2.
- The public kernel artifact is now built from a filtered release tree rather
  than the private monorepo root. CI and the release workflow use that same
  builder, preventing excluded agent adapters from hiding missing imports.
- Standalone kernel commands no longer import the separately packaged Codex
  Guard. `custodian --version`, help, the console, and every registered
  subcommand are exercised from a clean wheel outside the source checkout.
- Added a PEP 668-safe managed installer. It stages and health-checks a private
  runtime before switching, keeps the prior runtime for rollback, exposes
  ordinary commands without venv activation, and has a data-preserving managed
  uninstall.
- Added a real PyPI 0.4.0-to-0.4.1 upgrade regression that verifies the CLI and
  preserves synthetic vault, ledger, Paladin, and Talaria data.
- Fixed the developer installer creating a venv and then accidentally using
  the caller's Python instead of the new runtime.
- Release metadata now includes all runtime dependencies and policy presets,
  excludes private adapters and Caduceus, and mirrors the release README,
  license, and installer.
- Release qualification now installs the exact immutable wheel and runs the
  documented bare commands from clean state. Codex Guard setup also resolves
  its bundled plugin outside a source checkout.

### Gate controls

- Added Open and Protected gate modes to the CLI, numbered menu, and console.
  Open mode can notify for each automatic pass or run quietly; both modes keep
  tamper-evident receipts. Existing `developer-open` settings migrate to
  `open`.

## [0.4.0] — 2026-07-21

### Ledger visibility now defaults to nothing, not self

`LedgerAccessPolicy.visible_harnesses()` used to always include the calling
harness (`visible = {harness}`), so `list_receipts` returned a harness's own
decision history -- reasons, tools, verdicts -- with zero configuration. The
agent being governed is exactly the party a denial log exists to constrain;
self-visibility handed it an oracle to probe the enforcement boundary and
route around it. No harness now sees any receipts by default, including its
own; the operator grants visibility explicitly, self included, the same way
cross-harness grants already worked. `verify_receipts` (chain-integrity
proof only -- `{valid, count}`, no reasons/tools/verdicts) is unaffected;
it carries no oracle value. The write path was already fully kernel-
mediated (`guard_action` is the only caller of `chain.append()`, and only
with kernel-computed content) -- this closes the matching read-side gap.

### Per-harness ledger isolation

Every receipt and approval is now stamped with the harness that produced it
(server-side, from the same trusted-adapter identity already pinned for
`guard_action` -- never a model-supplied argument). By default a harness
sees only its own history; a new MCP tool, `list_receipts`, returns a
harness's own receipts and clearly denies (not silently empties) a request
for another harness's without an explicit grant. Grants are managed via a
new `custodian/control/ledger_access_policy.py` (`custodian console`'s new
`[G]` key) -- e.g. "let opencode see codex's ledger" -- scoped optionally to
one trusted model id, following the same shape as the existing filesystem
and approval policies. The operator's own console/CLI view is unaffected:
the isolation boundary is agent-to-agent, not operator-to-agent. One
physical hash-chained receipt log is kept (not split per harness), matching
this module's existing tamper-evidence design; isolation is enforced at the
query boundary. 22 new tests.

### Second adversarial-review pass -- 15 more bugs found and fixed

A 9-agent review covering codex_guard core, opencode_guard + control-plane,
the executor/console CLI, and all remaining bundled skills/dashboard/
frontend files not yet independently reviewed.

- **CRITICAL**: an argv-list shell command (`["git","push","--force",...]`,
  the shape a real coding agent actually uses) was str()'d directly into its
  Python repr, whose stray quotes/brackets/commas broke every risk-inference
  pattern requiring whitespace between words -- silently defeating the
  "risk can never be lowered" guarantee for exactly this tool-call shape.
- **CRITICAL**: "workspace" (the containment boundary) is a value the
  caller/model itself declares, with no independent anchor -- declaring
  `$HOME` or `/` as the workspace made the entire filesystem "inside the
  workspace." Now denied outright; ordinary project subdirectories are
  unaffected.
- `apply_patch` -- the actual tool name OpenAI's real Codex CLI uses for
  file edits -- was missing from the sensitive-config-write tool set,
  letting CI/CD pipeline files be silently rewritten with no escalation.
- Receipts leaked resolved filesystem paths verbatim via adapter denial
  reasons, contradicting the module's own "deliberately value-free" design.
- Console's pending-action list wasn't truly oldest-first despite its own
  label claiming so -- an operator could approve/deny a different action
  than the one shown.
- `executor approve/deny latest` resolved to the newest pending capability
  with no requester filter -- an operator could silently act on a different
  requester's pending capability.
- `find_pending_by_digest` didn't exclude denied capabilities -- a resend
  after an explicit denial got stuck on that same capability_id forever.
- A requester-length mismatch (128 vs. 256 chars) between two call sites
  meant a long requester's approved capability could never be found again.
- Console's interactive approve compared a record's digest to itself -- a
  tautology, not a check. Removed the parameter.
- 12 bundled-skill fixes: TwiML/XML injection in `twilio-voice-call`
  (crafted call-hijacking), missing destination validation (SSRF) in
  `http-get`/`http-post`/`web-scrape`/`webhook-post`, missing path
  boundaries in `file-read`/`file-list`/`base64-encode`/`hash-sha256`/
  `s3-get`, a NoSQL-operator denylist gap and unbounded `--limit 0` in
  `mongodb-find`, inconsistent URL quoting in `calendar-delete`/
  `calendar-update`, and a mislabeled trust band on `kv-set`.

53 new/updated regression tests. Full suite: 2560 passed, 1 skipped, 0 failed.

### Custodian Guard — Codex-native authority firewall

A new Codex plugin/MCP integration treating Codex as an untrusted proposer,
not its own authority: independent risk classification (the model cannot
downgrade `rm`, deploy, network, or credential operations to a "read"),
action-bound single-use expiring human approvals, value-free HMAC-linked
receipt chain, and a `custodian-codex` operator CLI (`setup`/`doctor`/
`status`/`approve`/`disable`). See `docs/CODEX_GUARD.md` for the full threat
model. 45 focused adversarial tests (`tests/test_codex_guard.py`).

### Governed OpenCode

`custodian-opencode` — the same guard, approval store, filesystem policy,
and receipt chain extended to OpenCode via a generated global plugin hook
that runs before every tool call. `opencode --auto` cannot override a
denial or escalation; `custodian-opencode` (the governed launcher) refuses
`--pure`, since OpenCode documents that flag as disabling external plugins.
Harness identity is assigned by the installed adapter, not accepted from the
model, so Codex- and OpenCode-specific rules cannot impersonate each other.
Unknown tools and delegated tasks fail closed. See
`docs/OPENCODE_INTEGRATION.md`.

### Control-plane foundation for the coordinated 0.4 release

`custodian/control/` — normalized control-plane policy, filesystem policy,
and service contracts shared by the Codex and OpenCode integrations, plus a
`custodian console` CLI surface. Operator rules apply to every action,
including ordinary reads/writes. See `docs/CONTROL_PLANE_TOPOLOGY.md`,
`docs/CONTROL_INTEGRATION_API.md`, `docs/CUSTODIAN_CONSOLE.md`,
`docs/FILESYSTEM_POLICY.md`.

### Dashboard / getcustodian.xyz — 3 more real bugs found and fixed

Found while auditing the live demo site end-to-end:

- **`dashboard/api/stripe_webhook.py`** — closed a TOCTOU race in the
  payment-dedup check: two near-simultaneous deliveries of the same Stripe
  event (Stripe does retry) could both pass the dedup check before either
  wrote, double-crediting revenue in the publicly-displayed P&L total. Same
  cross-platform locking pattern as `custodian/codex_guard/receipts.py`.
- **`dashboard/api/operator.py`** — `require_operator`'s
  `except Exception: return 401` failed safe but silently swallowed real
  internal bugs (e.g. a corrupted secrets file) as an indistinguishable
  "unauthorized" — now logs the exception before still denying. Separately,
  `/pending_code` and `/forward_code` were the last two demo-arc routes still
  gated behind operator auth, contradicting the demo's own design (the whole
  arc except `/reset` is meant to be anonymously reachable) — now public,
  each protected by its own rate limit instead (60/min/IP for the polled
  `pending_code`; the pre-existing 3/10min/IP Twilio-cost limit for
  `forward_code`).
- **`pages-frontend/operator.html`** — Step 7's refund button sent whatever
  was in the PaymentIntent field straight to `/refund` with no format check;
  if Step 1 never ran (or its budget was exhausted), this produced a
  confusing backend error instead of pointing the visitor back at Step 1.

Also fixed a pre-existing test (`dashboard/tests/test_ported_tour_guide_
system_2026_07_03.py`) whose own route-name assertions were inverted
(asserted the stale `/hermes` route present, current `/console` absent) —
silently never run as part of the main `tests/` suite.

### Deploy hazard closed — 6 copies of this repo were each deploying independently

At least 6 copies of this repo existed on this host, each with its own
working `deploy.sh` doing a direct `wrangler pages deploy` upload to the
same live Cloudflare Pages project — not git-triggered, no trace, whichever
copy deployed last silently won. This was the likely real cause of repeated
"things keep reverting" reports across sessions. The canonical development
repository is now the single source of truth; the other 5 copies' `deploy.sh` are
disabled. See `DEPLOYMENT.md`.

### Bundled skills — 5 more bugs fixed (independent Qwen bug-hunt review)

Found by a 3-agent Qwen3.6-35B adversarial review, independently re-verified
against the real invocation path before fixing (two of the review's other
claims did not reproduce and are not included here — see the session handover
for details).

- **`redis-set`/`redis-get`/`redis-delete`** — hand-built the raw Redis
  inline-command protocol via unescaped f-strings; a key or value containing
  `\r\n` could inject arbitrary additional Redis commands. Switched to the
  RESP array protocol, which is length-prefixed and can't be broken out of by
  delimiter bytes inside a value.
- **`postgres-query`/`mysql-query`** — declared band **L0** ("read-only, no
  real-world effects") but ran the caller's query verbatim with no validation
  at all — any write or DDL statement would execute. Added an allowlist
  (single `SELECT`/`WITH` statement only, comment- and string-literal-aware)
  matching the tool's own declared band and description.
- **`sqlite-query`** — its write-blocking check was a blocklist of a handful
  of keywords (`INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`CREATE`/`TRUNCATE`/
  `REPLACE`) that missed others entirely (e.g. `ATTACH DATABASE`). Replaced
  with the same allowlist approach as the two fixes above.
- **`file-write`** — its path-allowlist check (`realpath(path).startswith(
  realpath(ALLOWED))`) had no directory-separator boundary, so a sibling
  directory sharing a string prefix (e.g. `/tmp/allowed` vs.
  `/tmp/allowed-evil`) bypassed it.
- **`shell-exec`** — `python3` sat in the command allowlist at band **L2**
  ("autonomous, routine") with no argument restriction at all — unlike
  git/curl/find, there is no safe restricted subset of "run arbitrary code"
  reachable by denying a few flags, so it's removed from the allowlist
  entirely. (A `--workdir` restriction was also considered for this tool and
  reverted after re-checking against its own test suite: every allowlisted
  binary here already accepts arbitrary absolute-path arguments with no
  directory restriction, and `--workdir` is the only legitimate way to point
  `git log`/`git status` at a specific repo since `git -C` is already
  blocked — restricting it further would not close a distinct capability,
  only break intended, already-tested usage.)

First 0.4 release. Adds a first-class credential broker (`paladin`), Windows
support, backup/restore, and bulk credential onboarding — and carries a round
of money/security hardening with a regression test for every fix (each verified
to fail against the pre-fix code).

### `custodian setup` — one-command installer

Most users shouldn't need to know `custodian-kernel`, `paladin`, and
`custodian-talaria` are three different PyPI names. `custodian setup`
detects a local Hermes Agent install and orchestrates `pip install` for
the components you ask for (`--with talaria`, `--profile hermes`). Fails
closed by design: with no arguments it only detects and reports, never
installs anything without an explicit ask.

The explicit Hermes profile completes the job: it installs a compatible
Talaria version with the dashboard extra, installs its plugin and starter
policy, creates the local vault if needed, and enables the plugin when Hermes
is present. `custodian doctor --profile hermes` verifies the resulting setup.

### Talaria split into its own package

The Hermes Agent + NemoClaw integration suite, previously developed
alongside the kernel and shipped bundled in this distribution, is now its
own repo and PyPI package: [`custodian-talaria`](https://github.com/KeyArgo/talaria),
depending on `custodian-kernel[paladin]` through a normal version pin
instead of being force-versioned in lockstep with the kernel. `paladin`
stays in this distribution — it has no Hermes-specific code.

### Credential broker (`paladin`)

- Encrypted vault (AES-256-GCM, scrypt), deny-by-default grants, hash-chained
  audit, and egress-only secret injection — the agent holds a `paladin://` ref,
  never the value.
- **Backup / restore** to a single encrypted archive. Restore verifies the
  backup decrypts *before* touching the destination and saves any overwritten
  files to `*.pre-restore` first.
- **Bulk import** from many sources, all reporting names/kinds/counts only —
  never values:
  - `.env` files (single, or a whole tree),
  - **CSV** password-manager exports (Chrome, Firefox, Bitwarden, LastPass,
    1Password, KeePass) — offline, no CLI; the value/name columns are
    auto-detected from the header, and headerless `KEY,value` files work too,
  - **JSON** secrets dumps (flat `{"NAME": "value"}` or an array of
    `{name, value}`),
  - **Bitwarden** and **1Password** via their CLIs,
  - `discover` — report-only: shows where credentials live (`.env`, shell-rc
    exports, password-manager exports in Downloads/Desktop) and the exact
    command to import each.

### Universal ledger

- **A single, hash-chained, cross-process-safe audit ledger** (`custodian/universal_ledger.py`)
  now records every governed action's full lifecycle — `proposed` → `decided`
  → `escalated`/`approved`/`denied` → `executed`/`failed` — with a
  SHA-256 hash chain (tamper-*evident*, not tamper-*proof*; the limits of
  that claim are disclosed in the module itself) and an origin-bound
  genesis instead of a fixed literal. Wired into the real governed-tool
  execution path (`CustodianTool.invoke()`, not just the `custodian
  request`/`approve`/`deny` CLI flow), the inference router, and the kill
  switch/confirm CLI commands, which previously wrote only to the legacy
  JSONL audit log with no hash-chained record at all.
- Sanitizes every field at write time: bounded lengths, a `paladin://` ref
  format check, and a secret-shape scan reusing `secret_leak_guard`'s
  patterns — a caller cannot accidentally write a raw credential into the
  audit trail.

### Sandboxed, delegated tool execution

- **Every governed skill script now runs inside a filesystem/exec-confined
  sandbox by default** (`custodian/sandbox.py`, real `bwrap` — fresh
  PID/UTS/IPC/cgroup namespaces, the filesystem re-mounted read-only except
  the tool's own state and skill directories, `~/.ssh`/`~/.aws`/`~/.gnupg`/
  `~/.paladin` masked to an empty tmpfs). Fails closed — refuses to run a
  governed script at all — if bwrap or unprivileged user namespaces aren't
  available, unless explicitly opted out via `CUSTODIAN_ALLOW_UNSANDBOXED_TOOLS=1`.
  Deliberately does not isolate the network (most bundled skills need real
  API access); a per-tool destination allowlist (`custodian/egress_proxy.py`,
  opt-in via `allowed_hosts` in a skill's `SKILL.md`) closes the common case
  of a compromised skill's own SDK exfiltrating to an unintended host, short
  of full network isolation (deferred to its own 0.6.0 branch).
- **Delegated execution** (`custodian/executor/`, opt-in via
  `CUSTODIAN_EXECUTOR_SOCKET`): a separate OS process re-derives every
  kernel decision independently from its own copy of policy/authority
  state, and is the only code path that actually executes a governed
  script — the calling agent process can only propose an action over a
  Unix socket and holds no execution code of its own. Escalated actions
  mint a signed, digest-bound, single-use capability (HMAC-sealed, atomic
  consumption) that a human approves (`custodian executor approve`);
  re-sending the identical request then consumes it and executes, exactly
  once. `custodian/tools/registry.py`'s kernel-decision logic (previously
  duplicated per call path) is now the one shared `custodian/policy/gate.py`
  implementation behind the tool registry, the delegated executor, and the
  inference router.
- **`custodian/inference/router.py`'s LLM calls are now kernel-governed.**
  Previously bypassed the kernel entirely — no kill-switch check, no spend
  cap, no audit trail, unlike every registered tool. Now gates on the
  worst-case cost (`max_tokens` fully consumed) before any network call,
  reconciling the ledger down to the real token count afterward; an
  escalation fails closed (no interactive human-in-the-loop path exists in
  a chat/report-generation context).

### Supply chain

- Release artifacts (wheel, sdist, SBOM) are signed with keyless Sigstore/
  cosign signing via GitHub OIDC on every version-tagged release — no
  long-lived signing key to generate, store, rotate, or leak — with
  signature verification built into the release workflow itself.
  CycloneDX SBOM generated from the actual installed wheel's dependency
  closure, not the dev checkout.
- The kernel's own Ed25519 receipt-signing key can now rotate
  (`custodian.signing.SigningKeyRing`): retire an old key without
  invalidating receipts it already signed, or revoke one outright if it
  may be compromised — the single hardcoded-key model had no answer for
  either.

### Money path

- **Concurrent spends no longer lose money or blow the session cap.** Spends
  reserve budget under an OS advisory lock *before* charging; a failed charge
  releases the reservation. Was: two concurrent spends could each read a stale
  total, both charge, and record only one — money moved exceeding money
  recorded, cap breachable. Verified: 8 concurrent \$250 spends against \$1000
  → exactly 4 charged, recorded equals charged.
- **`daily_envelope` is now enforced on the pack/triage path**, and the router
  refuses to delegate to a remote Spark node whenever a gate the node cannot
  see (`daily_envelope`, `margins`, `no_self_dealing`) is configured — those
  always enforce locally, fail-safe.
- **Refunds cannot exceed the original charge in aggregate** (prior refunds are
  summed at the point money moves).
- **Money gates fail closed:** `daily_envelope`, `margins` and `no_self_dealing`
  now escalate to a human if a check errors, instead of silently continuing.

### Security

- **The tool registry's band-cap gate now checks the real requested amount,
  not a static declared default.** Was always built from the SKILL.md's
  static `cost_usd` (0.0 for most spend tools) regardless of what a caller
  actually asked for — verified live, a \$999,999.99 call to a fresh L2 tool
  sailed through as autonomous under a \$2.00 default cap.
- **`CustodianMiddleware`'s governed-route matching now normalizes the
  request path before comparison.** An exact-string-only match let a
  request differing only by a trailing slash, a doubled leading slash,
  case, or a decoded `%20` reach the downstream application completely
  ungoverned — a route configured to always require human approval let a
  \$999,999 request through as an ordinary 200.
- **`@govern`'s amount detection now binds to the real parameter named
  `amount`,** not "the first nonzero, non-bool number in the positional
  args" — a decorated function with another numeric parameter before
  `amount` (an id, a quantity) was gated on that decoy value instead of
  the real spend.
- **The Stripe webhook endpoint now rejects replays.** Signature
  verification was already correct, but the same valid, captured
  `(payload, signature)` pair could be resent any number of times and was
  credited every time — now bounded by a timestamp-tolerance check plus
  de-duplication by the event's own Stripe id.
- **`paladin.backup.restore_backup()`'s pre-restore safety copy no longer
  clobbers a prior one.** Two ordinary, consecutive restores used to
  silently overwrite the first restore's saved "current vault" with the
  second's, contradicting the module's own documented invariant.
- A dashboard debug-log endpoint no longer follows a pre-planted symlink
  at its fixed `/tmp` path (a clobber/read primitive on a shared host), and
  its previously-unbounded fields are now length-capped like their
  siblings.
- **The DGX Spark remote-enforcement node (`spark-enforcement/enforce_server.py`)
  was completely broken** — its policy loader called two methods that don't
  exist on `Policy`, so every `/decide` call crashed (the crash happened to
  read as "node unreachable" to the caller's own fallback logic, masking it
  rather than fixing it). Restoring it surfaced a second, latent bug: an
  unauthenticated caller could forge `SpendRequest`'s opt-in revenue/cost/
  agent-id fields to defeat a margin or self-dealing gate this node's local
  policy configures, since nothing on the wire independently verifies them.
  The node now refuses to decide at all when its policy configures a gate
  it can't verify, instead of trusting attacker-suppliable input.
- Roughly 45 further bugs, each with a live reproduction and a regression
  test that fails against the pre-fix code, found via repeated rounds of
  adversarial review across the kernel, `paladin`, the guard adapters, the
  escalation/approval boundary, the ASGI middleware, and the dashboard —
  see the git history for the full list; too many to enumerate here
  individually.
- **Kernel and middleware inputs fail closed.** Non-finite monetary values,
  malformed or oversized governed request bodies, explicitly missing policies,
  and corrupted authority state can no longer fall through to permissive
  defaults.
- **Operator controls are authenticated end to end.** Money movement, approval,
  kill/resume, pending-code, SMS-forwarding, sandbox, and enforcement-mode
  mutations require a short-lived operator token; the getcustodian.xyz frontend
  obtains and supplies that token while read-only evidence remains public.
- **Tool subprocess environments are least privilege.** Tools no longer inherit
  unrelated host secrets, governance failure escalates instead of executing,
  event payloads are sanitized, and known credentials are redacted if a child
  echoes them.
- **Paladin egress requires HTTPS outside loopback**, rejects URL credentials,
  fragments, control characters, and request-framing headers, and removes a
  credential even when an upstream service reflects it in its response.
- Windows-shaped backslash paths are normalized before adapter path checks on
  every platform, closing a cross-platform self-protection bypass.
- Report delivery no longer succeeds when its kernel gate errors and no longer
  assumes the maintainer's email identity. Deployments configure their own
  verified sender.

- **Auto-downgrade can no longer escalate authority.** A downgrade recorded
  from a high-band task could raise a later request that had routed to a lower
  band; autorank now only ever lowers authority.
- **Enforcement-routing flags moved out of world-writable `/tmp`** to the state
  dir (guarded by `kernel-self-protection`); the legacy path is still read for
  backward compatibility.
- **`@govern` tamper snapshots moved out of `/tmp`** and keyed by qualified
  module + name; a tamper-drift denial is now audited instead of silent.
- Rename of the credential broker package to `paladin`, with a read-only
  compatibility surface for pre-rename vaults, refs, env vars, and audit chains
  (the on-disk format magic is honored, so existing vaults keep opening).

### Correctness / portability

- The installable verification kit is deployment-neutral: its optional live
  audit endpoint is supplied with `--dashboard-url` or
  `CUSTODIAN_VERIFY_DASHBOARD_URL`, never hardcoded to getcustodian.xyz.
- Nemotron visitor chat now drops an additional class of untagged response-
  construction directives observed in production instead of displaying model
  self-talk.
- Bundled tools never install packages dynamically at runtime; dependencies are
  resolved during the normal package installation process.

- Governed tools now run under `sys.executable`, not a hardcoded `python3`
  (the tool registry was non-functional on Windows).
- `tzdata` is declared as a dependency (timezone tools failed on Windows and
  slim images).
- Quoted `.env` values containing `#` are no longer truncated
  (`PASS="Str0ng #Pass!"` was imported as `Str0ng`).
- `custodian init` now initializes authority state (it created an empty state
  dir before, so every following command warned "no authority state found").
- `SqliteStorage` load→modify→save no longer crashes on the band field.

### Notes

- On Windows there is no in-process sandbox (that comes from an external,
  Linux-only helper); the control plane, crypto, guards, and audit are
  identical on both platforms. File-mode assertions (`0600`/`0700`) are
  POSIX-only and skip on Windows, where NTFS ACLs and AES-256-GCM provide
  at-rest protection.
