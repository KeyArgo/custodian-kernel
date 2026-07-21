# CUSTODIAN Console — Live Operator Firewall

The `custodian console` command provides a live, dependency-free terminal UI for
approving, denying, and policy-routing requests across all installed integrations
(Codex Guard and Executor Capabilities). It operates in a fail-closed loop: no
action is permitted until a human explicitly approves it or an auto-approve rule
matches.

## Quick Start

```shell
custodian console --state-dir /path/to/state
```

The dashboard refreshes every second and shows all pending requests ordered by
age (oldest first). Press a single key to act on the oldest pending item.

## Keyboard Commands

| Key | Action |
|-----|--------|
| `A` | **Approve once** the oldest pending request |
| `D` | **Deny** the oldest pending request |
| `I` | **Ignore** the oldest request for five minutes; it remains pending and unauthorized |
| `L` | **Lease** — add a one-hour, 25-use auto-approve rule for Codex write |
| `F` | **Filesystem scope** — interactive prompt to add a path access rule |
| `R` | **Rules** — show active approval rules and their modes |
| `K` | **Global stop** — adds a catch-all deny rule (requires confirmation) |
| `Q` | **Quit** the console |

Keys are case-insensitive. Only the oldest pending request is acted on (the one
at the top of the WAITING list). There is no need to specify an index — the
console always applies `[A]`, `[D]`, and `[I]` to the most stale visible item.
Ignore is only a display snooze: it never changes an approval record, and the
action remains blocked until explicitly approved.

## Display

The dashboard is composed of three sections:

1. **Header** — shows the total pending count, split by integration (Codex vs
   Executor), the last refresh timestamp, and the current policy status.
2. **Pending requests** — each item shows the source (`CODEX` or `EXEC`), time
   until expiry, requester identity, a short digest prefix, and the time since
   creation. The digest is a SHA‑256 hash of the action's canonical JSON — the
   raw action content is never stored or displayed (sanitized).
3. **Footer** — shows the number of filesystem scopes, keyboard shortcuts, and
   a brief explanation of approval semantics.

Hard denials remain visible in a red **BLOCKED ACTIONS** section after the
request ends. They are deliberately not presented as approvable requests:
the operator must review policy or use a separately trusted maintenance
workflow. A damaged receipt chain is also displayed as a blocking alert.

## Approve-Once Semantics

Every approval in Custodian is **single-use**. When you press `[A]`:

1. The pending record transitions from `pending` → `approved` and is sealed
   with an HMAC‑SHA256 tag.
2. The next action whose digest matches the approved record consumes it
   atomically via an O_EXCL claim file — exactly one caller wins.
3. After consumption, the record shows as `consumed` and cannot be reused.

This prevents replay attacks: a "yes" given to one specific action cannot be
applied to a different, more dangerous request.

## Leases vs Permanent Rules

### Leases

A **lease** is a temporary rule with bounded lifetime and usage. The `[L]` key
creates a lease that:

- **Duration**: expires after 1 hour
- **Uses**: auto-approves up to 25 matching actions
- **Scope**: Codex write actions in the current workspace
- **Effect**: matching requests skip the pending queue and execute immediately

Leases are ideal for interactive coding sessions where repeated write access is
expected and safe.

### Permanent Rules

A **permanent rule** has no `expires_at` or `max_uses` limit. It persists until
explicitly removed from the policy JSON file at
`state_dir/approval-policy.json`. Permanent rules can be:

- **`ask`**: requires human approval (the default for every adapter)
- **`auto`**: automatically approves matching actions (never for governance,
  credential, destructive, production, or money actions)
- **`deny`**: blocks matching actions unconditionally

To remove a permanent rule, delete its entry from the JSON file or use the
`[R]` key to inspect rule IDs and edit manually.

### Comparison

| Property | Lease | Permanent |
|----------|-------|-----------|
| Expiry | 1 hour | None |
| Use limit | 25 | None |
| Persistence | Deleted after expiry | Until manually removed |
| Creation | Press `[L]` | Edit policy JSON |
| Typical use | Interactive session | Long-term policy |

## Enforcement Levels

Each rule has one of three enforcement levels:

- **`deny`** — the action is rejected immediately. No approval is possible.
- **`ask`** (default) — the action is held in the pending queue until a human
  approves or denies it.
- **`auto`** — the action is automatically approved if it matches the rule's
  scope (limited to non-dangerous action kinds).

Rules are evaluated newest-first. The first matching rule wins, so a deny rule
added via `[K]` takes precedence over older allow rules.

## Fail-Closed Behavior

The console **fails closed** in two ways:

1. **Policy-level**: if no rule matches a request, the default enforcement is
   `ask` — the action is held for human review. No action is ever permitted
   without either a matching `auto` rule or explicit human approval.
2. **Runtime-level**: if any key handler or dashboard draw raises an exception,
   the console catches the error, displays it, and continues the refresh loop
   rather than crashing. A stuck or compromised state never silently approves.

## Global Stop (`[K]`)

Pressing `[K]` with confirmation adds a catch-all `deny` rule:

- `adapter=*`, `action_kind=*`, `tool=*`, `req=*`
- Mode: `deny`

Once active, **no pending or future request can be approved**. The deny rule
persists in the policy file and survives a console restart. To resume
operations, remove the deny rule from `state_dir/approval-policy.json`.

Because this action blocks all operations, a confirmation dialog is always
shown before the rule is added.

## Filesystem Scopes (`[F]`)

The `[F]` command opens an interactive prompt to add a filesystem access rule.
You supply:

- **Harness**: the sandbox runtime (e.g., `codex`)
- **Model**: an AI model identifier, or `*` for all models
- **Access**: `read` or `write`
- **Allow roots**: path prefixes the model can access
- **Deny roots**: path prefixes always blocked (deny overrides allow)
- **Enforcement**: `routed` (reject the action) or `brokered` (intercept and
  proxy to a safe sandbox path)

## Architecture Notes

- The console imports `ApprovalStore` from `custodian.codex_guard.approvals`
  and `CapabilityStore` from `custodian.executor.capability` — these are
  independently implemented (same design, not shared imports) because Custodian
  must never depend on Codex Guard's integration-specific code.
- Both stores use HMAC‑SHA256 sealed JSON records with O_EXCL claim files for
  atomic single-use consumption.
- The console has no dependency on Twilio, Twisted, or any network service. It
  works entirely against local filesystem state.

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| No requests shown | No pending requests exist, or all have expired (default TTL is 5 minutes) |
| `[A]` does nothing | Request may have expired after the dashboard was drawn; wait for refresh |
| `[K]` shows confirmation but does not add rule | Confirmation was declined (type `y` to confirm, any other key cancels) |
| Dashboard shows "Error drawing dashboard" | State directory missing or corrupted; check `--state-dir` path |
| Key presses not registered | Terminal may not be in raw mode; try a standard terminal emulator |
