# Security Model

_Last updated: 2026-06-29_

## Core principle

The agent cannot approve its own escape because the authority boundary is
enforced outside the agent's process, outside its code path, and outside
any file the agent can write.

## The self-approval bug that was found and fixed

During the build, an earlier version of the spend script accepted an
`--approved-by` flag on the unprivileged request path. An agent running
that script could simply pass `--approved-by "itself"` and execute any
spend without real verification. There was no architectural barrier — just
a convention that the flag should not be used that way.

The fix had three parts:

1. **The request path has no `--approved-by` flag.** Not validated away,
   not discouraged — structurally absent. `custodian request` (and the
   underlying `spend_v2.py` script) has no way to assert approval.
2. **The only path to escalate is `custodian approve <CODE>`** (and
   `approve_v2.py`), gated on a real external verification check
   (`check_response()`) that the requesting process cannot satisfy on its
   own.
3. **The approval code never enters the agent's process.** Twilio generates
   the code, sends it via SMS to the operator's phone, and holds it. The
   `PendingApproval` record stores only amount, description, reason, and
   timestamp — never a code. No file the agent can read contains the code.

## Privilege separation

The CLI is deliberately two commands with non-overlapping capabilities:

- **`custodian request`** — reads policy and state, decides, saves a
  pending record if needed. Cannot approve. Takes no `--approved-by` flag.
- **`custodian approve <CODE> --approved-by NAME`** — requires both an
  external verification check (Twilio Verify API) and a human name. Only
  this path can record an approval.

## Why this is stronger than a convention

The conventional approach is a single process that checks "am I allowed?"
before executing. The agent could skip the check, modify the check's
result, or pass a fake approval flag. The agent controls its own process,
so anything inside that process is ultimately the agent's decision.

This design makes the approval authority a **separate binary** with
**different arguments**, running in a **different invocation**, calling a
**separate external API** (Twilio) that has **no file-based state in common**
with the requesting process. The agent cannot even formulate the approve
command correctly — it needs a code that exists only on Twilio's servers
and the operator's phone.

## `ApprovalBackend.check_response()`

This method is abstract (`ApprovalBackend.check_response` has
`__isabstractmethod__ = True`). Every backend must implement it, and every
implementation must hit a real external source to verify the code. The
shipped implementation (`TwilioVerifyBackend.check_response`) makes an
HTTP POST to `verify.twilio.com` — it never compares against a locally
stored value, never reads a local file for the answer, and never reads an
environment variable containing a code.

A backend that could be satisfied from local state would be a
self-approval vulnerability by design. The abstract method definition and
the regression tests enforce that no such backend can be added without
being caught.

## What verification exists

- **`test_self_approval_regression.py`** — 7 tests that:
  - Confirm `spend_v2.py` has no `--approved-by` flag (precise flag-set pinning)
  - Confirm `approve_v2.py` requires both a code and an `--approved-by` name
  - Confirm `approve_v2.py` calls `check_response()` *before* `execute_spend()`
  - Confirm `check_response` is abstract (every backend must define it)
  - Confirm `TwilioVerifyBackend.check_response` makes an HTTP call to
    `verify.twilio.com` (not a local comparison)
  - Confirm `PendingApproval` never stores a code field
- The fix was proven by deliberately reintroducing the bug, confirming the
  test failed, then restoring the fix.
- Real Twilio Verify and Stripe (test-mode) integrations have been
  exercised end-to-end in the development sandbox.

## The kill switch as a security control

A separate, blunter mechanism from the cap/escalation system above: an
operator-only override that makes every request `DENIED`, regardless of
band or amount, with no exception. It exists for the case the cap system
doesn't cover -- not "this amount needs approval," but "something about this
agent or this situation seems wrong, stop everything until a human looks."

The agent has no path to set or clear it. `custodian.policy.evaluator.decide()`
accepts a `killed: bool` parameter, but nothing in the agent's own request
path can supply `True` -- only `custodian kill --by <name>` (a CLI command
requiring a human-attributed name) writes that state. The live, authoritative
`spend.py` checks it via a read-only `sqlite3` query against the same database
the CLI writes to; `spend.py` has no write access to that table.

## What does not exist

- No third-party security audit has been performed.
- No formal verification of the privilege-separation property.
- No penetration testing beyond what the regression tests cover.

## Threat model boundaries

| Threat | Mitigated by |
|---|---|
| Agent passes `--approved-by` to approve itself | No such flag exists on the request path |
| Agent reads the pending approval file to find the code | PendingApproval stores no code — never has |
| Agent modifies a backend to skip verification | Backend name must be in `VALID_APPROVAL_BACKENDS`; only `twilio_verify` and `none` are valid |
| Agent calls `check_response()` with a fake answer | `check_response()` hits Twilio's servers, not local state |
| Agent bypasses `check_response()` and writes approval audit entry directly | Requires a separate privileged process; the agent only has the request CLI |
| Agent engages/clears its own kill switch | No code path from the agent's request CLI writes `kill_switch`; only `custodian kill`/`custodian resume` do, both requiring a human name |

## Security posture vs. a signed-execution governor (cyberware.systems)

Custodian and cyberware.systems share the same core idea — the agent proposes,
a governor outside the agent's process decides — and Custodian implements the
same building blocks:

| Guarantee | Custodian | Notes |
|---|---|---|
| Value-free protocol (only metadata crosses the wire, never secrets) | Yes | `ValueFreeClient`, `sanitize_dict` (redacts secret keys incl. `authorization`/`cookie`, at any depth incl. inside lists), and the Paladin vault (values only leave via `paladin exec` into a child env) |
| Secrets held in an encrypted vault | Yes | Paladin: scrypt KDF + AES-256-GCM; grants are deny-by-default and band-ceilinged; audit chain is HMAC-hash-chained with constant-time compare |
| Content-addressed / tamper-checked skills | Partial | `@govern`'s tamper check snapshots each governed function's source SHA and denies on drift; snapshots live under `~/.custodian` (on the self-protection list) |
| Tamper-evident receipts (integrity) | Yes | `GovernedReceipt` SHA-256 fingerprint covers every semantic field |
| **Unforgeable receipts (authenticity)** | Yes | `custodian.signing`: Ed25519-signed receipts — a receipt cannot be forged by anyone without the kernel's private key. Verify against the kernel's public key. |
| Cross-platform reproducibility | Yes | Receipt hashing is byte-identical on Linux/Windows/macOS (`json` `ensure_ascii`, pinned by a determinism test); CI runs the suite + a clean wheel install on Ubuntu **and** Windows |
| Kill switch cannot be bypassed | Yes | Enforced fail-closed locally on every surface (CLI, `@govern`, tool registry); a configured remote enforcement node can never override an engaged kill switch |
| Confined signed-execution principal (delegated mode) | No | cyberware's `exod` (Ed25519-signed step results from a confined Linux process) has no direct Custodian equivalent; Custodian governs in-process + optional remote enforcement |
| Formal model-checking (TLA+/Apalache/TLAPS) | No | Custodian relies on a large regression suite and a self-approval regression test, not machine-checked proofs |

**Honest bottom line.** For the guarantees most deployments depend on — secrets
never crossing the wire, an encrypted vault, a kill switch that truly can't be
bypassed, and receipts that are both tamper-evident and (when signed)
unforgeable — Custodian is on par. cyberware goes further on two axes Custodian
does not yet claim: a confined signed-execution principal and machine-checked
formal proofs. Custodian does not fake either; both are listed as limitations
above rather than advertised.
