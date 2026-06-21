# Policy Language Reference

Policies are YAML files. A policy defines authority bands, rules for
assigning requests to bands, and escalation behavior. Match conditions are
a fixed, small vocabulary — not a general-purpose expression language.
This is a deliberate simplicity choice: a general condition grammar would
be harder to validate, test, and audit.

## Example: the default policy

The default policy (shipped at `custodian/policy/presets/default.yaml`) is:

```yaml
version: "1.0"
default_band: L2

bands:
  L0:
    max_spend: 0
    requires_approval: false
    description: "Read-only, no real-world effects"
  L1:
    max_spend: 0.50
    requires_approval: false
    description: "Trivial autonomous spend"
  L2:
    max_spend: 2.00
    requires_approval: false
    approval_backend: twilio_verify
    description: "Standard autonomous band -- escalates above its cap or the session budget"
  L3:
    max_spend: 50.00
    requires_approval: true
    approval_backend: twilio_verify
    description: "Always requires human approval, regardless of amount"
  L4:
    max_spend: null
    requires_approval: true
    approval_backend: twilio_verify
    description: "Unlimited, but always requires approval -- for critical/irreversible actions"

rules: []

escalation:
  timeout_seconds: 600
  on_timeout: deny
  retry_count: 0
```

## Top-level fields

| Field | Required | Type | Description |
|---|---|---|---|
| `version` | yes | string | Must be `"1.0"`. |
| `default_band` | yes | string | The band assigned when no rule matches. Must be defined in `bands`. |
| `bands` | yes | mapping | Band name → band configuration. |
| `rules` | no | list | Ordered list of match rules. Evaluated in declaration order; first match wins. |
| `escalation` | no | mapping | Escalation timeout and behavior. |

## Bands

Each band key is an arbitrary name (by convention L0–L4). The name is
case-sensitive.

| Field | Required | Type | Description |
|---|---|---|---|
| `max_spend` | no | float or null | Per-action maximum. `null` = unbounded. Negative values are rejected. |
| `requires_approval` | no | bool | If true, every action in this band must be approved by a human, regardless of amount. |
| `approval_backend` | conditional | string | Required when `requires_approval` is true. Must be `"twilio_verify"` or `"none"`. Only `twilio_verify` actually sends a challenge. |
| `description` | no | string | Human-readable description of the band. |

If `requires_approval` is true and no `approval_backend` is set, validation
fails. If `approval_backend` is set to anything other than `twilio_verify`
or `none`, validation fails.

## Rules

Rules are evaluated in declaration order. The first rule whose match
condition is satisfied assigns the request to a band. If no rule matches,
the request uses `default_band`.

Each rule has:

| Field | Required | Type | Description |
|---|---|---|---|
| `match` | yes | mapping | Conditions that trigger this rule. |
| `assign_band` | yes | string | The band to assign when this rule matches. Must be defined in `bands`. |

### Match conditions

All match conditions are optional within a `match` block. A rule with an
empty `match` block matches everything (acts as a catch-all). When
multiple conditions are specified, all must match (logical AND).

| Condition | Type | Description |
|---|---|---|
| `skill` | string | Matches when the request's `--skill` flag equals this value. |
| `context.<flag>` | bool | Matches when `--context <flag>=true` (or `=false`) is passed. The `<flag>` part is the context key. When set to `true` (or omitted, which defaults to `true`), matches on truthy; when set to `false`, matches on falsy. |
| `spend_estimate_gt` | float | Matches when the request amount is strictly greater than this threshold. |

Example with context flag — documented in `custodian/policy/schema.py` and
tested in `tests/test_policy.py::TestDecide::test_rule_context_flag_matches`:

```yaml
rules:
  - match:
      skill: provision-server
      context.critical: true
    assign_band: L4
```

This would match `custodian request --amount 1.00 --description "..." --skill provision-server --context critical=true`.

## Escalation

| Field | Type | Default | Description |
|---|---|---|---|
| `timeout_seconds` | int | 600 | How long a pending approval stays valid. Positive integer. |
| `on_timeout` | string | `"deny"` | What to do when a pending approval expires. Must be `"deny"` or `"retry"`. |
| `retry_count` | int | 0 | How many times to retry before giving up. Must be >= 0. |

## Validation

Use `custodian validate <policy.yaml>` to check a policy file without
running a request:

```bash
custodian validate my-policy.yaml
```

This loads the policy, parses all bands and rules, checks that every
referenced band exists, validates all field constraints, and reports any
errors with the exact field name and problem.
