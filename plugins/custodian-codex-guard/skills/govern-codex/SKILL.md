---
name: govern-codex
description: Govern consequential Codex tool calls with Custodian before execution, including writes, network access, credentials, destructive commands, production changes, and money movement.
---

# Govern Codex

Enforcement is mandatory and automatic: Custodian installs a Codex `PreToolUse`
hook (`custodian-codex setup`) that the harness runs before **every** tool call
and that can block it outright. This holds even under `approval_policy = "never"`
or a trusted project, and does not depend on you calling any tool. A blocked call
returns `permissionDecision: "deny"` with the reason; a consequential action you
have not had approved is blocked with a `custodian-codex approve ID --digest
DIGEST` instruction — ask the operator to run it, then retry the **identical**
action once. You cannot split a forbidden operation into smaller calls to evade
the hook; each call is evaluated independently.

The `guard_action` MCP tool below remains available for previewing a decision or
for surfacing receipts, but it is no longer what enforces policy. Use it to
classify a proposal using exactly one action kind:

- `read`: local read-only inspection
- `test`: local test or build with no external side effect
- `write`: ordinary workspace edit
- `network`: any outbound network request or remote read
- `credential`: resolving, injecting, or using a credential
- `destructive`: deletion, overwrite, history rewrite, or irreversible action
- `production`: deployment or production-state change
- `money`: payment, refund, purchase, or financial commitment
- `governance`: changing policy, audit, approval, vault, or the guard itself

Pass the actual tool name and structured arguments, plus a stable requester ID
for this Codex session. Never put a raw secret in
the call; use a `paladin://` reference. Treat the verdict mechanically:

- `autonomous`: proceed with the exact evaluated action.
- `escalation_required`: stop, show the returned approval ID, and ask the human
  to run the exact `custodian-codex approve ID --digest DIGEST` command returned
  by Guard. Call `guard_action` again with that same ID and the exact same
  action. The verdict itself is not approval.
- `approved`: proceed once with the exact evaluated action. Any argument change
  requires a new request; never reuse an approval ID.
- `denied`: do not execute. Explain the denial without exposing sensitive data.

If Guard is unavailable, malformed, or returns an unknown verdict, fail closed
for writes and consequential actions. Do not split one forbidden operation into
smaller calls to evade policy. After a demo, call `verify_receipts` to prove the
local decision chain has not been edited.
