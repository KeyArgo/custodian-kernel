# Custodian 0.5.0 — Codex Hackathon Release Plan

Status: release contract, not yet released
Owner worktree: `/mnt/homes/Development/custodian-dev-codex`, branch `feat/0.5.0-codex`
Submission: OpenAI Build Week, Developer Tools
Deadline: July 21, 2026 at 5:00 PM Pacific

## Release thesis

Custodian 0.5.0 is the first release in which a coding agent is treated as an
untrusted proposer rather than its own authority. The hackathon product is
**Custodian for Codex**:

> An authority firewall that lets Codex work autonomously inside declared
> boundaries while secrets, destructive actions, network access, production
> changes, money movement, and governance changes are independently denied or
> bound to explicit human approval.

This is not a Codex-themed demonstration of a generic library. It must install
as a Codex product, govern a real Codex workflow, and produce evidence a judge
can verify without credentials or access to InovinLabs infrastructure.

## Honest go/no-go assessment

This entry is **competitive, not likely**. The event lists more than 43,000
participants and awards only first and second place in Developer Tools. The
submission gallery is hidden, so there is no defensible way to calculate the
number or quality of competing entries. Do not represent a win as probable.

It remains rational to enter because most of the difficult foundation already
exists, the work improves the real product even if it does not place, and the
idea maps directly to all four judging criteria. Custodian also has unusually
strong external validation for a hackathon entry: a prior first-place result,
an extensive adversarial suite, and a working authority/credential foundation.

Continue only while the following are attainable before the submission cut:

- a real Codex installation and mechanical enforcement boundary;
- one coherent allow/deny/escalate/approve demonstration;
- a clean judge repository and one-command offline proof;
- a public sub-three-minute video with spoken Codex/GPT-5.6 explanation;
- the required `/feedback` session ID.

If mechanical enforcement or a testable Codex installation is still missing at
the submission freeze, stop feature development. Either submit a deliberately
narrow, honest governed-executor product or decline to submit; do not spend the
remaining hours decorating an advisory-only prototype.

## Winning strategy

The release should attempt to be the strongest **complete product**, not the
largest security platform. Every hour must improve one of the published judging
criteria:

| Criterion | Winning evidence | Failure mode to avoid |
|---|---|---|
| Technological Implementation | Real Codex plugin/boundary, action digest approval, Paladin mediation, adversarial tests, dated Codex-built history | Generic Custodian code with a thin Codex label |
| Design | One-command setup, `doctor`, 60-second demo, plain-language verdicts, clean uninstall | Architecture impressive but judges cannot run it |
| Potential Impact | Specific developer/MSP threat, real prompt-injection-to-secret/deploy scenario, prior Custodian validation | Abstract “AI governance for everyone” claims |
| Quality of Idea | Authority firewall: the agent cannot classify or approve its own consequential action | Positioning as another sandbox, prompt guard, or scanner |

The video and README must make the central novelty understandable in one
sentence: **the coding agent is the proposer, never its own authority**.

### Demonstration story that judges will remember

Use one continuous scenario rather than unrelated test cases:

1. Codex receives a poisoned repository instruction asking it to read `.env`,
   push a change, and deploy it.
2. A normal source inspection and test pass autonomously.
3. The secret read is denied below model context.
4. The push/deploy is independently recognized even when described as a read.
5. The operator approves the exact safe deployment action.
6. A one-character argument change and approval replay both fail.
7. Paladin performs the approved credentialed operation without exposing the
   value to Codex.
8. The receipt chain verifies; editing one decision makes verification fail.

This single story demonstrates implementation, design, impact, and novelty
without asking judges to mentally assemble separate features.

### Proof hierarchy

Prefer evidence in this order:

1. live behavior in a real Codex session;
2. clean one-command judge demo;
3. adversarial tests for the exact attacks shown;
4. inspectable implementation and dated Git history;
5. architecture claims.

Never lead with test counts. Test counts support the result but are not the
product experience.

### Time allocation until submission

- 45% mechanical enforcement, approval integrity, and Paladin mediation.
- 20% installer, `doctor`, clean judge repository, and platform smoke tests.
- 20% video rehearsal/recording and Devpost copy.
- 10% adversarial review and final regression runs.
- 5% contingency for upload, permissions, and submission-form failures.

Do not spend deadline time on a general dashboard redesign, Capability Pack
marketplace, Docker orchestration, MSP tenancy, Claude/Antigravity adapters,
brand exploration, or unrelated 0.4.0 website work.

### Submission insurance

- Create the Devpost draft immediately and populate every known field.
- Capture the `/feedback` session ID before context loss or switching sessions.
- Record a viable video take before attempting a polished second take.
- Upload early and test YouTube playback logged out.
- Make the repository public or verify both judging accounts can access it.
- Keep a release artifact and demo transcript locally in case the live site or
  package index is unavailable during judging.
- Freeze a known-good commit before final documentation/video edits.

## Release set and repository boundaries

The private `custodian-dev` monorepo remains the development source of truth.
The public release is split into focused, sanitized repositories and packages:

| Release | Public repository | Distribution | Responsibility |
|---|---|---|---|
| 0.5.0 | `KeyArgo/custodian-kernel` | `custodian-kernel` | Provider-neutral action contract, policy, approval binding, ledger, adapters, Paladin module |
| 0.5.0 | `KeyArgo/custodian-codex` | `custodian-codex` | Codex plugin, hook/MCP bridge, installer, policy translator, demo and judge experience |
| 0.1.x | `KeyArgo/talaria` | `custodian-talaria` | Hermes/NemoClaw integration; compatible consumer of the kernel, not part of the Codex entry |

Paladin remains bundled with `custodian-kernel` in 0.5.0 for compatibility and
one-command installation, but retains a strict module boundary. A future
distribution split must not be mixed into the hackathon deadline.

Nothing in the kernel may mention Codex, the hackathon, getcustodian.xyz, an
InovinLabs deployment, or a personal machine. Nothing in the Codex integration
may duplicate kernel policy, receipt, ledger, or Paladin cryptography.

## Product surfaces

### Judge and Codex user

```bash
pipx install custodian-codex
custodian-codex setup
custodian-codex demo
custodian-codex doctor
```

### Existing Custodian user

```bash
custodian setup --with codex
```

### Operator

```bash
custodian-codex status
custodian-codex approvals list
custodian-codex receipts verify
custodian-codex lock
```

The dedicated installer is a thin Codex-facing wrapper over shared setup
primitives. It must not fork the actual product or hardcode this website.

## Required architecture

```text
Codex proposes a typed action
            │
            ▼
Custodian Codex hook / governed MCP execution boundary
            │
            ├── canonicalize exact tool + arguments + workspace + destination
            ├── independently infer minimum risk (never trust model label)
            ├── run mandatory kernel guards
            ├── evaluate authority policy
            └── write value-free decision receipt
                    │
       ┌────────────┼──────────────┐
       ▼            ▼              ▼
  autonomous     escalation       denied
       │            │
       │            └── action-bound, expiring, single-use approval
       │                            │
       └──────────────┬─────────────┘
                      ▼
             governed executor
                      │
             optional Paladin ref
       (value injected below model context)
                      │
                      ▼
           redact output + ledger result
```

Codex's own sandbox and approvals remain defense in depth. Custodian must state
exactly which calls it intercepts and never claim control over an unrelated
tool runner.

## Harness control and operator escape design

When a user explicitly selects enforcement, Custodian must mechanically own the
supported Codex or Hermes tool boundary. The model may propose actions and
explain objections, but it cannot bypass, disable, reconfigure, approve, or
uninstall its governor through that boundary.

“Control” means control of consequential tool execution routed by the supported
harness integration. It does not mean controlling model text, unrelated tools,
the operating system, or a second unintegrated agent process. Every integration
must publish its precise coverage.

### Modes

Every harness has one explicit mode:

| Mode | Behavior | Intended use |
|---|---|---|
| `enforce` | Autonomous actions execute; denied actions stop; consequential actions require exact approval; guard failure stops consequential execution | Normal protected operation |
| `observe` | Evaluate and record decisions but do not block; display a persistent warning that protection is not enforced | Initial rollout and troubleshooting |
| `off` | Integration is disabled and makes no protection claim | Explicit operator choice or uninstall |

Mode changes are never inferred and never occur automatically after an error.
There is no hidden “fail open into observe” path. Setup must clearly ask which
mode the user wants and default a new security installation to `enforce` only
after its self-test succeeds.

### Preventing agent self-disablement

- The control plane and policy live outside every governed workspace.
- The harness exposes proposal/execution tools to the model, never control-plane
  commands such as mode change, approval, unlock, policy replacement, or
  uninstall.
- Control requests are authenticated over an OS-permissioned local socket or
  equivalent IPC to a governor process running with a separate identity where
  supported.
- Policy and mode changes require an interactive operator channel and are
  recorded in the ledger.
- The agent cannot satisfy the confirmation by printing text, invoking the CLI,
  setting an environment variable, editing configuration, or replaying an old
  approval.
- Windows service ACLs and POSIX user/socket permissions receive platform tests.

### Avoiding operator lockout

Fail-closed protection must not hold the user's development environment hostage.
Ship three independent recovery paths:

1. **Normal control:** `custodian configure`, the local operator dashboard, and
   `custodian mode observe|enforce` through authenticated interactive control.
2. **Timed pause:** `custodian pause --for 15m --reason "repair integration"`.
   The pause expires automatically, is visibly displayed, and is audit logged.
3. **Break glass:** `custodian recovery disable <harness>` using an offline
   recovery secret or OS administrator identity. This path works even when the
   governor, policy parser, ledger, plugin, or Python environment is damaged.

Break glass disables the integration; it does not grant the agent an execution
token. It must be documented during setup, tested before declaring the install
ready, and impossible to trigger through a model-visible tool.

The installer must also print and persist a manual recovery document containing
only non-secret instructions: plugin locations, service name, configuration
path, backup path, and safe removal steps. A user with local administrator access
always retains the final ability to stop the service and remove the integration.

### Configuration after installation

```bash
custodian configure                 # guided configuration
custodian mode                      # show effective mode and coverage
custodian policy show --effective   # compiled policy, including defaults
custodian policy edit               # validate, preview diff, then activate
custodian policy rollback           # restore last-known-good policy
custodian doctor --prove            # harmless real allow/deny integration test
custodian integrations status       # Codex/Hermes coverage and hook state
```

The local dashboard exposes the same operator functions with plain-language
presets, per-rule explanations, and an effective-policy preview. It never sends
policy, vault metadata, or receipts to getcustodian.xyz unless the operator
separately configures a remote service.

Configuration activation is transactional:

1. parse and validate a candidate;
2. compile it without changing live state;
3. display the semantic diff and newly allowed capabilities;
4. require stronger confirmation for weakened protections;
5. atomically activate it;
6. retain a last-known-good version and rollback command;
7. write a value-free governance event to the ledger.

Corrupt configuration never overwrites the active policy. If no valid active or
last-known-good policy exists, enforcement stops consequential actions and
prints the out-of-band recovery path.

### Paladin choice

Custodian governance works with or without Paladin:

- **Custodian only:** governs action authority; credentials remain the user's or
  harness's responsibility.
- **Custodian + Paladin:** additionally keeps secret values outside model
  context and mediates their use through scoped grants and restricted egress.

Setup recommends Paladin when credentialed tools are detected but requires
explicit consent. Disabling Paladin never silently substitutes plaintext secret
delivery; credentialed operations stop until the operator deliberately chooses
another credential strategy.

## Non-negotiable security invariants

1. Unknown actions, malformed requests, unavailable guards, ledger failures,
   and approval verification failures deny consequential operations.
2. The model may overstate risk but can never lower the independently inferred
   risk class.
3. Approval is not a Boolean. It binds the canonical action digest, workspace,
   requester/session, policy version, expiry, and one-time nonce.
4. Changing any evaluated argument invalidates approval. There is no
   time-of-check/time-of-use gap between approval and execution.
5. Codex never receives a plaintext secret. `paladin://` references are
   resolved only inside an authorized executor or destination-restricted
   request broker.
6. Policy, approval keys, vaults, receipt keys, ledger files, hooks, and Guard
   code are self-protected even when located inside the workspace.
7. Receipts never contain prompts, file contents, command lines, arguments, or
   secret values. They contain hashes and bounded decision metadata.
8. Receipt and ledger writes use restrictive permissions, locking, atomicity,
   and durable flush behavior on Windows and POSIX.
9. Symlink, junction, case-folding, UNC, alternate-data-stream, relative-path,
   quoting, shell-chain, and executable-alias evasions have regression tests.
10. Network destinations are parsed structurally. Userinfo, redirects, DNS
    rebinding-sensitive resolution, and host confusion cannot bypass policy.
11. A denied operation cannot be decomposed into smaller calls to evade the
    policy envelope.
12. Installation failure cannot silently leave a user believing protection is
    active. `doctor` distinguishes installed, registered, enabled, and proven.

## Scope required for 0.5.0

### P0 — must ship for the hackathon

#### Operator control without agent escape or user lockout

- Explicit `enforce`, `observe`, and `off` modes with no automatic downgrade.
- Mode and policy stored outside the governed workspace and self-protected.
- Model-visible tools cannot change mode, policy, approval, or installation.
- Guided `configure`, effective-policy display, validation, atomic activation,
  and last-known-good rollback.
- A tested timed pause and documented break-glass removal path that remain
  usable when the integration is damaged.
- `doctor --prove` confirms an actual harmless allow and deny through the
  installed harness boundary.
- Persistent status output makes `observe`, `paused`, and `off` impossible to
  mistake for enforced protection.

#### Codex-native enforcement

- Validate the current Codex plugin manifest against the current Codex plugin
  interface.
- Use a supported Codex lifecycle hook for mechanical pre-action enforcement
  if available. If universal interception is not supported, expose a governed
  executor and describe the exact boundary honestly.
- Keep MCP tools small and typed:
  - `guard_action`
  - `execute_governed_action` (only if the integration owns execution)
  - `approve_action` or a local operator equivalent
  - `verify_receipts`
  - metadata-only `list_secret_refs`
- Fail closed for consequential calls when the boundary is unavailable.

#### Action-bound approval

- Canonical action schema and stable digest.
- Pending approval store outside the workspace.
- Single-use, short-lived approval token.
- Explicit operator identity and reason.
- Consumption performed atomically with execution authorization.
- Replay, mutation, expiry, wrong-session, and concurrent-consumption tests.

#### Paladin mediation

- Metadata-only secret discovery.
- Exact requester grant such as `codex:<session-or-executor>`.
- Destination and maximum-band checks before resolution.
- Reference is removed before child arguments are formed.
- Value enters only the approved child environment or request transport.
- Child output is scanned and redacted before it reaches Codex.
- No generic `get_secret` tool and no plaintext fallback.

#### One-command installation

`custodian-codex setup` must:

1. Detect Codex and Python requirements.
2. Install/register the plugin and MCP server using supported Codex surfaces.
3. Ask for or infer only the current workspace; never authorize a home drive or
   filesystem root by default.
4. Create restrictive state and receipt storage.
5. Offer Paladin without requiring it.
6. Run a harmless allow/deny self-test.
7. Print a short ready/not-ready result and exact repair command.

Also ship `doctor`, `status`, `demo`, `update`, and `uninstall`. Setup and
uninstall must be idempotent. No secrets may enter shell command arguments.

#### Judge demo

The deterministic, offline demonstration must show:

| Case | Expected result |
|---|---|
| Local source read | autonomous |
| Workspace edit/test | autonomous |
| `.env` or private-key read | denied |
| `rm`, push, or deploy mislabeled as read | independently escalated |
| Approval for exact deploy action | accepted once |
| Reuse or argument mutation | denied |
| Receipt verification | valid |
| Edited receipt | tampering detected |

The demo must finish in under 60 seconds and make no network call or external
state change.

#### Product polish

- README answers what it is, why Codex needs it, how to install, exact threat
  model, limitations, Windows/Linux support, uninstall, and 60-second proof.
- Friendly errors contain a repair action and never a raw secret or traceback.
- CLI output uses plain language and remains readable without ANSI color.
- `--json` exists for status/doctor/receipt verification where practical.
- No dependency on getcustodian.xyz for installation or judging.

### P1 — ship only after every P0 gate is green

- Unified append-only ledger record shared by decisions, approvals, Paladin
  resolutions, and execution outcomes.
- Signed Codex capability manifest with a fixed roster and file hashes.
- Publisher/release provenance for the plugin and wheel.
- Minimal local read-only dashboard for decisions, approvals, and receipt
  verification.
- Destination-restricted HTTP execution broker.
- Policy presets: `developer-safe`, `review-only`, and `production-locked`.

### Deferred from the hackathon cut

- General marketplace and multi-publisher Capability Packs.
- Full Docker/bwrap/gVisor delegated executor.
- Multi-tenant MSP control plane.
- Claude, Copilot, Antigravity, and additional harness integrations.
- Cloud-hosted fleet management.
- Formal verification beyond state-machine/property tests.

These are valuable 0.5.x/0.6 features, but adding unfinished infrastructure
would reduce hackathon design and implementation quality.

## Testing and assurance matrix

### Unit and adversarial

- Every action class and inference rule.
- Caller risk downgrade attempts.
- Command chaining, quoting, nested shells, PowerShell, and Windows paths.
- Protected surface read/write/delete/rename/symlink attempts.
- Secret formats and redaction evasions.
- Approval mutation, replay, race, expiry, and policy-version mismatch.
- Receipt truncation, reordering, deletion, modification, and wrong key.
- Guard, storage, and broker failure injection.

### Integration

- Actual stdio MCP initialize/list/call exchange.
- Fresh Codex session sees and calls the installed integration.
- Installed hook/boundary blocks a real proposed operation.
- Paladin reference is used without appearing in model-visible output.
- Setup, setup-again, doctor, update, and uninstall.

### Platforms

- Linux, Python 3.11 and current Python.
- Windows PowerShell, Python 3.11 and current Python.
- Paths containing spaces and non-ASCII characters.
- Optional Docker smoke test; Docker is not required for desktop use.

### Artifact and supply chain

- Build wheel and source distribution from clean checkout.
- `twine check` all artifacts.
- Inspect wheel/sdist file inventories.
- Install with dependencies into a new environment, never an editable checkout.
- Secret/PII/internal-URL scan of public tree and complete public history.
- Reproducible or explained artifact hashes.
- GitHub Actions on Windows and Linux.

## Release acceptance criteria

0.5.0 is releasable only when all are true:

- P0 behavior is implemented and reviewed.
- Focused and full suites have zero unexpected failures.
- Clean wheel installation passes on Windows and Linux.
- A fresh Codex session completes the judge workflow.
- Installer reports enabled and proven, not merely files present.
- Public repository is sanitized and contains setup/sample data/license.
- README distinguishes pre-existing Custodian work from Build Week work.
- Limitations explicitly state the enforcement boundary.
- Demo requires no credential, account, rebuild, or private service.
- Video is public, under three minutes, has spoken audio, and works logged out.
- The GPT-5.6 Codex `/feedback` session ID is recorded.
- Devpost description, repository, category, video, supported platforms, and
  testing instructions are complete.
- No tag or PyPI publication occurs until the final artifact install succeeds.

## Deadline execution plan

### Cut 1 — security-complete core

1. Freeze the action schema.
2. Implement action-bound approvals and TOCTOU-safe consumption.
3. Implement Paladin metadata and mediated execution path.
4. Confirm the Codex enforcement surface and correct all claims.
5. Expand adversarial tests until all P0 invariants are covered.

### Cut 2 — product-complete experience

1. Extract/package `custodian-codex` cleanly.
2. Implement `setup`, `doctor`, `status`, `demo`, and `uninstall`.
3. Install into a fresh Codex session on Linux and Windows.
4. Finish README, architecture diagram, limitations, and sample policy.

### Cut 3 — submission-complete evidence

1. Freeze code except critical fixes.
2. Run full suites and artifact checks.
3. Record one continuous demo take, then edit only for dead time and captions.
4. Upload publicly and test logged out.
5. Record `/feedback` session ID and exact Codex/GPT-5.6 contribution.
6. Submit early enough to correct Devpost upload or permission failures.

If Cut 1 is not complete, do not disguise the MCP advisory workflow as
universal enforcement. Reduce scope to the boundary that is genuinely
mechanical and demonstrate it exceptionally well.

## Three-minute video

- **0:00–0:15:** An injected instruction asks Codex to read a token and deploy.
- **0:15–0:30:** “The agent proposes. Custodian decides. Paladin mediates.”
- **0:30–1:25:** Live allow, deny, independent escalation, exact approval,
  mutation/replay denial.
- **1:25–1:50:** Verify receipts, edit one, show tamper detection.
- **1:50–2:15:** Run `doctor`; show one-command install and Windows/Linux support.
- **2:15–2:40:** Show adversarial tests and the dated Codex-built branch/history.
- **2:40–2:55:** Impact and limitation: safe autonomy without claiming an OS
  sandbox or control over unintegrated tools.

## Devpost positioning

Category: **Developer Tools**

Title: **Custodian for Codex**

One-line description:

> An authority firewall that independently governs consequential Codex actions,
> mediates secrets below model context, binds human approval to the exact action,
> and proves every decision with tamper-evident receipts.

The submission should emphasize four differentiators:

1. Authority rather than another prompt guard.
2. Independent classification rather than trusting the agent's label.
3. Secret-mediated execution rather than handing credentials to the model.
4. Action-bound approval and evidence rather than a generic confirmation box.

## Post-submission continuation

After submission, keep 0.5.0 stable and build 0.5.x in this order:

1. signed Capability Packs;
2. unified durable ledger and signed checkpoints;
3. authenticated isolated executor and destination broker;
4. optional Docker/Linux confinement;
5. MSP multi-tenant control plane;
6. Claude, Copilot, and Antigravity integrations against the same contract.
