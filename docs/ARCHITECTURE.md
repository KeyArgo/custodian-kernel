# Architecture

Custodian enforces spending authority through a three-layer design: a
**policy DSL** that defines who can spend what, a **decision engine** that
evaluates each request, and a **privilege-separated approval path** that
prevents the agent from approving its own escalation.

## Data types

The core types are in `custodian/types.py`:

- **`SpendRequest`** — what the agent wants: an amount, a description,
  optional skill name, optional recipe/target fields. No approval code or
  approval flag.
- **`AuthorityState`** — the agent's current authority: which band it's in,
  its per-action cap, session cap, and how much it has spent this session.
- **`Decision`** — the policy engine's verdict on a request: `AUTONOMOUS`,
  `ESCALATION_REQUIRED`, or `DENIED`, along with a human-readable reason.
- **`PendingApproval`** — stored when a request escalates. Contains only
  amount, description, reason, and timestamp. Never contains an approval
  code — the code exists only on Twilio's servers and the operator's phone.
- **`AuditEntry`** — one event in the append-only log: what happened, how
  much, who approved/denied it, Stripe PaymentIntent ID if executed.

## Request → Decide → Execute flow

```
Agent                    Custodian CLI              Policy Engine
  │                           │                          │
  │  custodian request        │                          │
  │  --amount X               │                          │
  │  --description "..."      │                          │
  │  [--skill NAME]           │                          │
  │  [--context FLAG=true]    │                          │
  │ ──────────────────────>   │                          │
  │                           │  Load policy.yaml        │
  │                           │  Load AuthorityState     │
  │                           │  (from SQLite)           │
  │                           │                          │
  │                           │  decide(request, state,  │
  │                           │    policy, skill,        │
  │                           │    context)              │
  │                           │ ──────────────────────>  │
  │                           │                          │
  │                           │  <── Decision ────────── │
  │                           │                          │
  │                           │  ┌─────────────────────────┐
  │                           │  │ Verdict?               │
  │                           │  ├─────────────────────────┤
  │                           │  │ AUTONOMOUS → print,    │
  │                           │  │   done (no real        │
  │                           │  │   payment executed by  │
  │                           │  │   CLI)                 │
  │                           │  │                        │
  │                           │  │ ESCALATION_REQUIRED →  │
  │                           │  │   save PendingApproval │
  │                           │  │   to SQLite            │
  │                           │  │   send Twilio Verify   │
  │                           │  │   SMS to operator      │
  │                           │  │   print "use approve"  │
  │                           │  │                        │
  │                           │  │ DENIED → print         │
  │                           │  └─────────────────────────┘
  │                           │
  │  <── result ───────────── │
  │                           │

--- Separate escalation path (operator's phone / separate process) ---

  Operator                   Custodian CLI              Twilio Verify
    │                           │                          │
    │  Receives SMS code        │                          │
    │                           │                          │
    │  custodian approve <CODE> │                          │
    │  --approved-by "Alice"    │                          │
    │ ──────────────────────>   │                          │
    │                           │  Load PendingApproval    │
    │                           │  Check expiry            │
    │                           │                          │
    │                           │  check_response(code)    │
    │                           │ ──────────────────────>  │
    │                           │   <── approved/rejected  │
    │                           │                          │
    │                           │  If approved:            │
    │                           │    Clear PendingApproval │
    │                           │    Append AuditEntry     │
    │                           │    (approved event)      │
    │                           │                          │
    │  <── result ───────────── │                          │
```

## The privilege-separation property

The critical architectural property is that the `request` path and the
`approve` path are separate CLI commands, with different argument sets, and
only the `approve` path can escalate:

- **`custodian request`** has no `--approved-by` flag. It cannot assert
  approval. It reads policy and state, decides, and either prints the
  autonomous verdict or saves a pending record for the approve path.
- **`custodian approve <CODE> --approved-by NAME`** requires both a real
  verification code (checked against Twilio Verify's servers) and a human
  name. It goes through `check_response()` before recording the approval.
- **`ApprovalBackend.check_response()`** is abstract — every backend must
  implement it, and the only shipped implementation
  (`TwilioVerifyBackend`) makes an HTTP call to Twilio's servers. It
  cannot be answered from local state the requesting process could have
  written.

This means self-approval is structurally impossible: the unprivileged path
cannot assert approval (no flag for it), the privileged path requires an
external verification check the agent cannot satisfy on its own, and the
approval code is never stored where the requesting process can read it.

## Policy engine

The policy DSL (`custodian/policy/schema.py`, `loader.py`, `evaluator.py`)
is a fixed-vocabulary YAML format, not a general expression language. A
policy defines:

- **Bands** — named authority levels (L0 through L4 by convention), each
  with a max spend, whether approval is required, and which backend to use.
- **Rules** — ordered match conditions (by skill name, context flags, or
  spend-amount threshold) that assign a request to a band. First match wins.
- **Escalation config** — timeout, what to do on timeout (deny or retry),
  retry count.

The `decide()` function in `evaluator.py` takes a `SpendRequest`, the
current `AuthorityState`, and the loaded `Policy`, runs the rules, checks
the band's cap and session budget, and returns a `Decision`.

## Storage

Only one storage backend is shipped: SQLite (`custodian/storage/sqlite.py`).
It uses WAL mode for concurrent reads, with three tables:

- `authority_state` — single-row table (enforced by `CHECK(id=1)`)
- `audit_log` — append-only, auto-incrementing rows
- `pending_approval` — single-row table (enforced by `CHECK(id=1)`)

## Approval backends

Only one backend is shipped: `TwilioVerifyBackend`. It uses Twilio's Verify
API to send an SMS code and check the response. The code is generated and
held by Twilio's servers — it is never returned to the requesting process
or written to any file the agent can read.
