# Custodian Codex — restart handover
<!-- Historical note: this was originally written while "Custodian 0.5.0"
     was still the planned separate release name for the Codex Build Week
     work. That decision changed -- everything ships together as Custodian
     0.4.0 instead. The branch name feat/0.5.0-codex predates this and was
     left as-is since it's already pushed; only the release/version
     references below were corrected. -->


Last updated: 2026-07-20 (America/Denver)

## Objective

Finish and submit **Custodian Guard** to OpenAI Build Week in the Developer
Tools category. The entry is the new Codex-native authority firewall built on
Custodian—not the entire pre-existing Custodian platform.

Core message:

> Codex can propose an action, but it cannot approve itself.

Do not claim guaranteed interception of every Codex/native tool. Custodian
governs operations routed through its plugin/MCP boundary and complements
Codex sandboxing and operating-system isolation.

## Canonical repository and branch

- Canonical checkout:
  `/mnt/homes/Development/custodian-dev-codex`
- Repository:
  `https://github.com/inovinlabs/custodian-dev`
- Branch:
  `feat/0.5.0-codex`
- Latest completed checkpoint:
  `aa01090 security(codex): harden judge path and cross-platform authority`
- Branch is pushed and matched GitHub when this handover was written.
- Do **not** tag a release or merge into `main` without the user's explicit
  instruction.

Because the sandbox can write `/home/dev` but not `/mnt/homes/Development`
without approval, the patch-safe working clone is:

`/home/dev/custodian-codex-work`

Normal workflow:

1. Edit and test in `/home/dev/custodian-codex-work`.
2. Commit on `feat/0.5.0-codex`.
3. Fast-forward the canonical checkout:

   ```bash
   git -C /mnt/homes/Development/custodian-dev-codex fetch \
     /home/dev/custodian-codex-work feat/0.5.0-codex
   git -C /mnt/homes/Development/custodian-dev-codex merge --ff-only FETCH_HEAD
   git -C /mnt/homes/Development/custodian-dev-codex push origin feat/0.5.0-codex
   ```

Avoid `/home/dev/custodian-dev` and the ordinary
`/mnt/homes/Development/custodian-dev` checkout: other Claude/release sessions
have used those and may have unrelated dirty changes. Claude owns the 0.4.0
release track; this branch owns the Build Week/Codex work.

## Implemented product

Primary implementation:

- `custodian/codex_guard/guard.py`
  - typed action classes;
  - independent risk inference so the model cannot safely label `rm`, deploy,
    network, PowerShell deletion, or credential operations as a read;
  - sensitive CI, packaging, Codex, and agent configuration writes escalate;
  - Custodian adapters enforce workspace/path, secret, prompt-injection, and
    kernel-self-protection rules.
- `custodian/codex_guard/approvals.py`
  - exact action digest over tool, effective risk class, arguments, resolved
    workspace, requester, and policy version;
  - authenticated, expiring, single-use approval records;
  - atomic replay prevention;
  - mutation, wrong-requester, expiry, malformed-value, and tampering rejection.
- `custodian/codex_guard/receipts.py`
  - value-free HMAC-linked receipt chain;
  - no prompts, commands, file contents, arguments, or secret values persisted;
  - tampering verification and key validation.
- `custodian/codex_guard/mcp_server.py`
  - stdio MCP server;
  - `guard_action` and `verify_receipts`;
  - the model can request an approval but has no tool that can approve it;
  - approval failure, mutation, and replay are recorded.
- `custodian/codex_guard/cli.py`
  - `custodian-codex setup`;
  - `custodian-codex doctor`;
  - `custodian-codex status`;
  - `custodian-codex approve ID --digest DIGEST`;
  - `custodian-codex disable` as an operator-only recovery path that preserves
    evidence.
- `plugins/custodian-codex-guard/`
  - valid Codex plugin manifest;
  - MCP companion configuration;
  - governance skill.
- `.agents/plugins/marketplace.json`
  - repo-local `custodian-build-week` marketplace.
- `scripts/codex-guard-demo.py`
  - deterministic, no-network judge demo using the real MCP handler;
  - proves safe work, secret denial, independent reclassification, human-only
    approval, argument mutation rejection, single-use replay rejection, valid
    receipts, and receipt-tampering detection.

Console entry points in `pyproject.toml`:

- `custodian-codex`
- `custodian-codex-guard-mcp`

## Completed verification

From `/home/dev/custodian-codex-work`:

```bash
python3 -m pytest -q tests/test_codex_guard.py
```

Result: **41 passed**.

Full suite used the complete development environment:

```bash
/home/dev/custodian-dev/.venv-dev/bin/python -m pytest -qq
```

Result: **100% passed**. Collection reported **2,010 selected tests** and four
intentionally deselected tests.

Also passed:

```bash
python3 -m py_compile custodian/codex_guard/*.py scripts/codex-guard-demo.py
python3 /home/dev/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py \
  plugins/custodian-codex-guard
python3 scripts/codex-guard-demo.py
```

The repo-local marketplace was installed successfully with current Codex, and
the plugin appeared as installed/enabled. A raw MCP initialize and tools/list
exchange succeeded. A fresh temporary virtual environment successfully exposed
both console commands when its `bin` directory was active on `PATH`.

An isolated package build was attempted but the sandbox could not download
`setuptools` due restricted DNS, and the existing development venv lacked an
importable `setuptools.build_meta` for `--no-isolation`. This is an environment
limitation, not a passing artifact test. A final artifact build still needs to
be run in the release environment with build dependencies available.

## Local Codex state

The repo marketplace was added locally:

`custodian-build-week -> /home/dev/custodian-codex-work`

The plugin was installed and enabled locally. A new Codex thread is required
for Codex to load the plugin and its MCP tools. Do not assume the current or a
resumed old thread has reloaded it.

OpenAI developer-docs MCP was also configured previously as
`openaiDeveloperDocs`, but it may require a new thread before its tools appear.

## Highest-priority next actions

### 1. Prove the actual new-thread Codex experience

Start a fresh Codex thread from `/home/dev/custodian-codex-work` or the
canonical checkout. Confirm the `govern-codex` skill and MCP tools load.

Prompt:

> Use Custodian Guard to evaluate a production deployment deliberately labeled
> as a read. Do not execute it. Show the approval command and explain what is
> cryptographically bound to that approval.

Expected behavior:

- Codex calls `guard_action`.
- Guard independently returns `escalation_required` and a command shaped like:

  `custodian-codex approve ID --digest DIGEST`

- Run that command in a separate human/operator terminal.
- Codex calls `guard_action` again with the exact same action and approval ID.
- Guard returns `approved` once.
- Mutation or replay returns `denied`.

Capture this interaction for the video. If the plugin does not load, diagnose
that before adding product features.

### 2. Perform a clean Windows PowerShell smoke test

The user specifically needs Windows support. In a clean Windows environment:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e .
custodian-codex setup
custodian-codex doctor
py scripts\codex-guard-demo.py
py -m pytest -q tests\test_codex_guard.py
```

Also verify that a PowerShell `Remove-Item` and `Invoke-WebRequest` proposal is
classified as consequential.

### 3. Record the video and submit

Follow:

`docs/BUILD_WEEK_SUBMISSION_PLAYBOOK.md`

The video must emphasize the actual Codex plugin, separate operator approval,
mutation/replay failure, and tamper-evident receipts. Do not make the general
website, MSP roadmap, Stripe demo, or entire kernel the lead story.

Before submitting:

- run `/feedback` from the Codex session where the majority of core work was
  built and copy the Session ID;
- create a public YouTube video with spoken audio under three minutes;
- verify the video while logged out;
- make the repository public or grant the official judging accounts access;
- include supported platforms, setup, sample use, testing, and the honest
  enforcement boundary;
- submit before the published deadline.

### 4. Build final artifacts only if time remains

The Devpost judge path can use the source checkout and editable install. Do not
delay the submission video or `/feedback` merely to publish 0.4.0 to PyPI.
This work ships together with the rest of Custodian 0.4.0, not as a
separate release.

## Remaining risks and claim discipline

1. **Harness boundary:** `guard_action` authorizes a digest, but Custodian does
   not universally intercept a separate native tool runner. The Codex plugin
   and skill must route relevant actions through the MCP boundary. Say this
   plainly.
2. **No model self-approval:** there is intentionally no MCP approval tool.
   Keep approval only in the operator CLI.
3. **No raw secret retrieval:** Paladin references are classified as credential
   operations. Do not add a generic model-callable `get_secret` tool.
4. **Website separation:** getcustodian.xyz may consume Custodian, but the
   kernel/plugin must never be hardcoded to that website or its operator.
5. **Recovery:** `custodian-codex disable` is the explicit operator escape
   hatch. It preserves receipts and approval evidence.
6. **No release tag yet:** the user explicitly asked not to tag until ready.

## What most improves the chance of winning

Do not expand to Claude, Hermes, Antigravity, MSP multi-tenancy, or a broad
future feature set before submission. Those are product-roadmap items. The
highest-leverage remaining proof is:

1. one clean install;
2. one real Codex plugin interaction;
3. one separate operator approval terminal;
4. one memorable two-minute-forty-second story;
5. one honest explanation of the boundary;
6. `/feedback` and Devpost completed correctly.

The entry should be called **Custodian Guard**, not a long suite name. The
memorable line is: **“Codex can move fast. It just cannot mint its own
authority.”**

## Key documents

- `docs/BUILD_WEEK_SUBMISSION_PLAYBOOK.md` — exact entry copy, judge path, and
  timed video script.
- `docs/CODEX_GUARD.md` — threat model and Build Week handoff.
- `docs/RELEASE_PLAN_0.4.0_CODEX.md` — full strategic and technical plan.
- `plugins/custodian-codex-guard/README.md` — plugin installation and contract.
- `tests/test_codex_guard.py` — focused adversarial regression suite.

## Restart instruction for the next AI

Read this file, `docs/BUILD_WEEK_SUBMISSION_PLAYBOOK.md`, and the current Git
status before acting. Continue on `feat/0.5.0-codex`; preserve separation from
Claude's 0.4.0 work. First prove the plugin in a new Codex thread and perform
the Windows smoke test. Do not redesign the repository or add integrations
until the submission-critical path is complete.
