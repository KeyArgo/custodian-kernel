# Custodian Guard for Codex — Build Week handoff

For the exact entry copy, judge commands, and timed video script, see
[`BUILD_WEEK_SUBMISSION_PLAYBOOK.md`](BUILD_WEEK_SUBMISSION_PLAYBOOK.md).

## What is new after July 13, 2026

The existing Custodian kernel, Paladin vault, and guard-adapter framework are
the foundation. The Build Week work is a new Codex-native enforcement surface:

- a repo-local Codex plugin and governance skill;
- a dependency-free MCP server exposing `guard_action`, `verify_receipts`,
  and `list_receipts`;
- the ledger is kernel-internal, not agent-facing: every receipt and approval
  is stamped with the harness that produced it (server-side, never a
  model-supplied value), and no harness sees any receipts by default —
  not even its own. The agent being governed is exactly the party a denial
  log exists to constrain; letting it read its own reasons/tools/verdicts
  would turn the ledger into an oracle it could probe to learn the
  enforcement boundary and route around it. Visibility (a harness's own
  history, another adapter's, or both) is only ever something the operator
  grants explicitly via a `LedgerAccessPolicy` rule, managed from `custodian
  console`'s `[G]` key. Not physically separate storage (one shared,
  hash-chained receipt log, matching this module's existing tamper-evidence
  design) — isolation is enforced at the query boundary. The write path is
  fully kernel-mediated too: no MCP tool ever exposes a raw append/delete —
  `guard_action` is the only writer, and it appends only what the kernel's
  own decision logic computes, never arbitrary model-supplied content;
- action-bound, expiring, single-use human approvals that the model cannot grant;
- a typed coding-action risk model independent of the model's own label;
- fail-closed composition of workspace, secret, prompt-injection, and
  kernel-self-protection guards;
- value-free HMAC hash-chained decision receipts;
- a deterministic judge demo and adversarial regression suite.

The dated Git history on `feat/codex-guard` distinguishes this work from the
pre-existing 0.4.0 code.

## Threat model

Guard assumes the model may be mistaken, prompt-injected, context-starved, or
actively attempting to understate risk. It therefore does not trust the
caller's action label. Known tool and command shapes independently raise the
minimum risk class. Unknown classes deny; guard crashes deny; raw credential
material denies; paths outside the declared workspace deny; changes to policy,
vault, audit, or guard surfaces deny.

The current plugin governs actions routed through its MCP decision boundary.
It does not claim to replace the host operating system sandbox or intercept a
separate, unintegrated tool runner. Codex's own sandbox and approval controls
remain defense in depth.

Approval is intentionally an operator-terminal operation. For a friendly path,
run `custodian-codex approve latest`; it shows the requester, full bound digest,
and human-readable time remaining, then requires interactive confirmation. The
long `--digest` form remains available when the operator wants to compare the
value shown by Guard independently. Approval never executes the action: it only
authorizes that exact digest for one subsequent consumption.

Receipt and approval state directories are private on POSIX, symlink state
roots are rejected, and receipt appends are serialized across MCP processes on
Windows and POSIX. HMAC chaining detects modification by processes that do not
possess the local signing key; it is not a substitute for OS account isolation
against an attacker who controls both the receipt file and its key.

## Three-minute video outline

1. **0:00–0:20 — Problem.** Coding agents can move faster than permission
   systems: one injected instruction can read a token, push code, or deploy.
2. **0:20–0:40 — Architecture.** Codex proposes an action; Custodian evaluates
   it outside model context; only an autonomous verdict proceeds; all decisions
   produce value-free receipts.
3. **0:40–1:35 — Live demo.** Run `python scripts/codex-guard-demo.py`. Point
   out safe test/edit, `.env` denial, and `rm`/deploy claimed as reads but
   independently escalated.
   Then show `custodian-codex approve ID`: changing the approved command or
   replaying the approval is denied.
4. **1:35–2:05 — Evidence.** Show `verify_receipts`, the tamper rejection, and
   `pytest -q tests/test_codex_guard.py`.
5. **2:05–2:35 — Codex collaboration.** Show the Build Week branch/session and
   explain that Codex implemented the MCP boundary, attacked the classifier,
   found relative-workspace resolution behavior, and added regression tests.
6. **2:35–2:55 — Impact.** Any developer or MSP can apply the same boundary to
   their own workspace and policies; nothing is hardcoded to our website.

Record at 1080p with terminal text enlarged. Use one continuous take where
possible, add spoken audio, keep it under three minutes, upload publicly to
YouTube, and verify playback in a logged-out browser.

## Submission checklist

- Confirm the session used GPT-5.6 and save the Codex Session ID for `/feedback`.
- Include a concise account of how Codex was used in the public README.
- Run the deterministic demo on a clean Linux environment and Windows.
- Run the full repository suite and plugin validator.
- Make the repository public, or share the private repository with the two
  official judging accounts listed in the rules.
- Add the public YouTube URL with audio and keep the video under three minutes.
- Submit before July 21, 2026 at 5:00 PM PDT.
