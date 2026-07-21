# Custodian control-plane integration API

Status: **normative** — this is the shared contract that Codex,
Talaria/Hermes, Paladin, and the delegated executor all implement.

## Purpose

Every integration (Codex MCP bridge, Hermes plugin, Paladin credential
broker, executor service) translates its own proposal and verdict shapes
into the neutral contracts defined here.  There is exactly one shared
approval gate — `ControlDecision` — and no adapter-specific competing
gate is exposed to the ledger, console, or any consumer.

## Contracts module

`custodian.control.contracts` — zero runtime dependencies beyond the
kernel's own types module.

### `EnforcementLevel`

```python
class EnforcementLevel(str, Enum):
    ADVISORY = "advisory"     # recommendation only
    ROUTED = "routed"         # cooperating caller consults Custodian
    BROKERED = "brokered"     # real capability lives behind executor
    NATIVE = "native"         # host lifecycle hook prevents bypass
```

Every adapter declares one of these.  No UI or documentation may describe
an `advisory` adapter as universal interception.

Methods:

- `strictest() -> EnforcementLevel` — returns `NATIVE`.
- `cannot_bypass() -> bool` — `True` for `BROKERED` and `NATIVE`.

### `ApprovalSemantics`

```python
class ApprovalSemantics(str, Enum):
    DENY = "deny"    # rejected outright
    ASK = "ask"      # human approval required before execution
    AUTO = "auto"    # may proceed autonomously within band
```

Alignment with `custodian.control.policy`'s `MODES` (`deny/ask/auto`) and
`codex_guard` verdicts is 1:1.

Methods:

- `requires_human() -> bool` — `True` only for `ASK`.
- `is_governed() -> bool` — `True` for `ASK` and `AUTO` (deny is not a
  governed action — it is a rejection).

### `CorrelationId`

```python
CorrelationId = str  # uuid4().hex — 32-char hex string
```

A single correlation token traced through every lifecycle transition
across all components: proposed → evaluated → allowed/denied →
approval_requested → approved → execution_started → succeeded/failed.

```python
def new_correlation_id() -> CorrelationId
```

### `ControlEvent`

```python
@dataclass(frozen=True)
class ControlEvent:
    event_type: str           # one of LIFECYCLE_TRANSITIONS
    correlation_id: str       # chains all events for one action
    source: str               # one of WELL_KNOWN_SOURCES
    action_digest: str        # SHA-256 hex of the action
    enforcement_level: EnforcementLevel
    approval_semantics: ApprovalSemantics
    timestamp: float
    event_data: frozenset     # sanitized (secrets stripped)
```

The `to_dict()` method applies `sanitize_dict` to `event_data` — secret-
bearing keys (`password`, `token`, `api_key`, `authorization`, `command`,
etc.) are replaced with `"[REDACTED]"` before serialization.

Valid `event_type` values (`LIFECYCLE_TRANSITIONS`):

```
proposed, evaluated, allowed, denied, approval_requested,
approved, execution_started, succeeded, failed, reversed
```

Valid `source` values (`WELL_KNOWN_SOURCES`):

```
codex, talaria, hermes, paladin, executor, kernel, console, operator
```

### `ControlEventSanitizer`

```python
class ControlEventSanitizer:
    @classmethod
    def sanitize(cls, raw: dict | None) -> dict
    @classmethod
    def sanitize_event_data(cls, raw: dict | None) -> frozenset
```

Reuses `custodian.types.sanitize_dict` to strip secret-bearing keys from
raw payloads before they enter the event log.

### `ControlDecision` — the single shared gate

```python
@dataclass(frozen=True)
class ControlDecision:
    verdict: str                    # autonomous | escalation_required | denied
    reason: str
    enforcement_level: EnforcementLevel
    approval_semantics: ApprovalSemantics
    correlation_id: CorrelationId
    action_digest: str
    approved_by: str
    timestamp: float
```

This is the **single gate** that every integration uses.  No adapter-
specific verdict shape is exposed to consumers.

Factory methods:

| Method | Verdict | Default semantics | Default enforcement |
|---|---|---|---|
| `ControlDecision.autonomous(reason=...)` | autonomous | AUTO | ROUTED |
| `ControlDecision.escalation(reason=...)` | escalation_required | ASK | ROUTED |
| `ControlDecision.denied(reason=...)` | denied | DENY | ROUTED |
| `ControlDecision.fail_closed(reason=...)` | denied | DENY | NATIVE |

Properties:

- `is_allowed -> bool` — `True` when verdict is `autonomous`.
- `is_denied -> bool` — `True` when verdict is `denied`.
- `is_escalated -> bool` — `True` when verdict is `escalation_required`.

### `EnforcementReport`

```python
@dataclass(frozen=True)
class EnforcementReport:
    adapter: str
    source: str
    correlation_id: CorrelationId
    action_digest: str
    declared_level: EnforcementLevel
    enforced_as: EnforcementLevel    # may be stricter than declared
    approved_semantics: ApprovalSemantics
    outcome: str                     # allowed | denied | escalated
    reason: str
    timestamp: float
```

Factory:

```python
EnforcementReport.from_decision(
    adapter="my-adapter",
    source="codex",
    decision=some_decision,
)
```

## Service module

`custodian.control.service.ControlService` — in-memory coordinator
(embed in the operator process; back with universal ledger in production).

### Component registration

```python
service.register("codex", "instance-1", EnforcementLevel.ROUTED)
service.unregister("codex", "instance-1")
service.heartbeat("codex", "instance-1")
reg = service.get_component("codex", "instance-1")
all_registrations = service.list_components()
```

An unregistered component's enforcement level defaults to `ADVISORY`
(fail-closed: the weakest level, causing no real enforcement, but never
crashing).

### Event management

```python
event = ControlEvent(event_type="proposed", ...)
service.emit(event)

by_corr = service.query_by_correlation(correlation_id)
by_src  = service.query_by_source("codex")
by_type = service.query_by_type("allowed")
recent  = service.recent_events(limit=50)
service.clear_events()
```

Event log is bounded (default 10,000 entries, FIFO eviction).

### Enforcement reporting

```python
service.report_enforcement("codex", "instance-1", EnforcementLevel.BROKERED)
level = service.get_enforcement("codex", "instance-1")
```

### Decision pipeline

```python
# Build a decision
decision = service.make_decision(
    verdict="autonomous",
    reason="within L1 band",
    correlation_id=cid,
)

# Emit it as a lifecycle event
event = service.emit_decision(decision, source="codex")
```

## Integration contract

Every integration (Codex, Talaria/Hermes, Paladin, executor) **must**:

1. Register with `ControlService` on start.
2. Emit a `ControlEvent` with `event_type="proposed"` for every action
   entering the authority boundary.
3. Translate the kernel's verdict into a `ControlDecision` (never expose
   an adapter-specific verdict shape to consumers).
4. Emit lifecycle events (`allowed`, `denied`, `approval_requested`,
   `execution_started`, `succeeded`, `failed`) tagged with the action's
   `correlation_id`.
5. Report the enforcement level actually applied via
   `service.report_enforcement()`.
6. Never embed secret values (`password`, `token`, `api_key`, `command`
   arguments, etc.) in `event_data` — the sanitizer strips them, but best
   effort happens at the source.

Every integration **must not**:

- Define its own competing approval gate or verdict enum for the ledger
  to consume.  Use `ControlDecision`.
- Expose `DENY` as anything other than a final rejection (fail-closed:
  no fallback to `ASK`).
- Accept enforcement weaker than what was actually applied.

## Compatibility

Existing `custodian.control.policy` (`ApprovalPolicy.decide` returns
`(mode, rule_id)` tuples) and `custodian.codex_guard` (`GuardDecision`,
`ApprovalRecord`) continue to work unchanged.  Integrations map their
existing verdicts *into* `ControlDecision` at the boundary — the old
internal shapes are not removed.

## Lifecycle transition flow

```
Codex/Hermes          Kernel / Policy          Executor          Paladin
    |                     |                       |                 |
    |-- proposed -------->|                       |                 |
    |                     |-- evaluated           |                 |
    |                     |-- allowed / denied ---|                 |
    |                     |-- approval_requested  |                 |
    |                     |<-- approved ---------|                 |
    |                     |                       |-- execution ---|
    |                     |                       |    started     |
    |                     |                       |                 |-- credential
    |                     |                       |                 |   resolved
    |                     |                       |-- succeeded ---|
    |                     |                       |-- failed -----|
```

Every arrow carries the same `correlation_id`.  The universal ledger
stores these events as a single traceable chain.
