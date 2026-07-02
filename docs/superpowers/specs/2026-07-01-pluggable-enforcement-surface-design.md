# Pluggable Enforcement Surface — Design

**Status:** Draft, pending user review
**Date:** 2026-07-01
**Context:** Custodian v0.2.0 governs one thing — dollar-denominated spend via
Stripe/Twilio. This spec generalizes the kernel to govern *any* agent action
(DB writes, infra changes, browser actions, arbitrary tool calls) without
rewriting the proven decision core (`policy/evaluator.py`, 1,346 tests).

## Problem

`@govern`, `CustodianMiddleware`, and the core types (`SpendRequest`,
`AuthorityState`, `BandConfig.max_spend`) are hard-typed to dollars:

- `govern.py:86-91` extracts "amount" by scanning kwargs then the first
  positional numeric arg — a heuristic that only makes sense for "charge
  this dollar figure."
- `middleware.py:63-65` reads `amount` directly out of the JSON request body.
- `types.py` (`SpendRequest.amount`, `AuthorityState.per_action_cap`,
  `AuditEntry.amount`) and `policy/schema.py` (`BandConfig.max_spend`) all
  assume the governed quantity is currency.

This caps Custodian's positioning at "a payments guard." The structural
pitch — "the kernel decides because it's outside the agent's process" —
applies to *any* action an agent takes, not just spend. Generalizing the
enforcement surface is the highest-leverage technical change available:
it builds on code that already exists (`@govern`, `CustodianMiddleware`,
`packs/` as a plugin pattern) rather than requiring a rewrite, unlike
multi-agent governance or a distributed runtime.

## Non-goals

- No change to `policy/evaluator.py` decision logic (`decide()` stays
  "compare a number to a cap," untouched).
- No change to existing Stripe/Twilio behavior, CLI commands, or the
  `custodian-verify` / `verify_kit.py` demo path.
- No distributed/multi-process runtime work (separate, later-stage effort).
- No multi-agent/org-tree governance (natural follow-on once this ships).

## Design

### 1. `ActionRequest` generalizes `SpendRequest`

Add two fields to a request type; keep `SpendRequest` as an alias so every
existing call site and test is unaffected:

```python
@dataclass
class ActionRequest:
    amount: float  # kept as-is: the numeric cost evaluator.decide() compares to caps
    description: str
    resource_type: str = "spend"      # NEW: "spend", "db_write", "infra_change", ...
    payload: dict = field(default_factory=dict)  # NEW: resource-specific data
    # ...all existing SpendRequest fields unchanged (recipe, to, message,
    # revenue, cost, requester_agent_id, recipient_agent_id, requested_at)

SpendRequest = ActionRequest  # backward-compat alias
```

`AuthorityState`, `Decision`, `AuditEntry`, `policy/evaluator.py::decide()`
require zero changes — they only ever consumed "a number vs. a cap."

### 2. Resource-type registry computes cost, not the decorator

New package `custodian/resources/`, structurally parallel to the existing
`custodian/packs/` plugin pattern:

```python
# custodian/resources/registry.py
CostFn = Callable[[dict], float]
_registry: dict[str, CostFn] = {}

def register(resource_type: str, cost_fn: CostFn) -> None: ...
def compute_cost(resource_type: str, payload: dict) -> float: ...
```

`resource_type="spend"` is pre-registered using **today's exact
amount-scanning heuristic**, moved (not rewritten) from `govern.py`. This
means step 2 is a refactor with the test suite staying green — no behavior
change for existing callers.

New resource types register their own `CostFn`:

```python
register("db_write", lambda p: p["rows_affected"] * SENSITIVITY_WEIGHTS[p["table"]])
register("infra_change", lambda p: BLAST_RADIUS_SCORES[p["change_type"]])
register("browser_action", lambda p: {"click": 1.0, "submit_form": 25.0}.get(p["action"], 100.0))
```

`@govern(resource_type="db_write", ...)` calls `compute_cost()` instead of
positional-arg scanning when `resource_type != "spend"`. `cap`, `band`,
kill switch, daily envelope, and receipts all work unchanged — they only
ever needed a number.

### 3. Policy language: `resource_type` scoping

`policy.yaml` bands gain an optional `resource_type` key so the same band
vocabulary (L0-L4) means different numeric caps per resource type:

```yaml
bands:
  L2:
    resource_type: spend
    max_spend: 50.00
  L2:
    resource_type: db_write
    max_spend: 500   # rows, not dollars — CostFn output, same field name
```

(Exact schema — single list of resource-scoped band entries vs. a nested
dict per resource type — is an implementation decision for the plan, not
this spec; both preserve the existing `BandConfig` shape.)

### 4. Middleware generalization

`CustodianMiddleware.register_path(path, band, cap, resource_type="spend")`
— extracts cost via `compute_cost(resource_type, json_body)` instead of
always reading `amount`. Governed routes for non-spend actions (e.g. an
agent's `/db/write` endpoint) get the same 402/403 + receipt behavior.

### 5. Reference resource type: `db_write`

Ship one resource type end-to-end as the proof the abstraction holds for
something that isn't money: `CostFn`, `policy.yaml` entries, a governed
example function, and tests, packaged the same way
`bundled_skills/payments/stripe-spend/` is packaged today — likely as
`custodian/resources/db_write/` with its own `policy.yaml` fragment.

Second resource type (`infra_change` or `browser_action`) follows once
`db_write` proves the pattern generalizes rather than merely fits one case.

## Rollout (test-safe increments)

1. Add `ActionRequest`/`resource_type`/`payload` with defaults preserving
   `SpendRequest` behavior exactly. Full suite green, zero other changes.
2. Move today's amount-extraction heuristic into
   `resources/registry.py` as the `spend` `CostFn`. Full suite green —
   refactor, not a behavior change.
3. Build `db_write` end-to-end (CostFn, policy entries, example, tests) as
   the reference implementation.
4. Extend `CustodianMiddleware`, update `docs/POLICY_LANGUAGE.md`, add
   `docs/RESOURCE_TYPES.md`.
5. Add a second resource type to confirm generalization.

Each step is independently testable and revert-safe. `custodian-verify`
and `verify_kit.py`'s Stripe/Twilio path are untouched throughout.

## Open questions (resolve during planning)

- Exact `policy.yaml` schema for resource-scoped bands (see §3 note).
- Where new resource-type packs live: `custodian/resources/<type>/` vs.
  folded into the existing `bundled_skills/` layout.
- Whether `GovernedReceipt`/audit ledger should render non-dollar costs
  with a unit label (e.g. "500 rows" vs. bare "500") for operator
  readability — currently deferred, not blocking for `db_write` proof.
- Which resource type to build second: pick based on target customer
  (deferred per user request — spec locks the pattern, not the roadmap).
