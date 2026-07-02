# Pluggable Enforcement Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize Custodian's `@govern`/`CustodianMiddleware` enforcement from dollar-only spend to a pluggable resource-type registry, so the kernel can govern DB writes, infra changes, and browser actions using the same bands, kill switch, and receipts — without touching the proven spend decision path.

**Architecture:** Add `resource_type`/`payload` fields to the request type (aliased so `SpendRequest` is unaffected), add a `custodian/resources/` registry of per-resource-type cost functions (mirrors the existing `custodian/packs/registry.py` plugin pattern), and add an optional `resource_bands:` block to the policy schema so band caps can be resource-scoped. The existing spend code path in `govern.py` stays byte-for-byte unchanged; non-spend resource types are a new branch that routes through the registry.

**Tech Stack:** Python 3.13, dataclasses, PyYAML, pytest (existing stack — no new dependencies).

## Global Constraints

- Zero behavior change for `resource_type="spend"` (the default) — every existing test in `tests/` must stay green after every task.
- `policy/evaluator.py::decide()`'s branching logic (kill switch, autorank, envelope, margin, self-dealing, cap checks) is not rewritten — only the one line that looks up `band_cfg` changes, to source it from the correct resource-scoped band map.
- New exception types follow the existing typed-hierarchy convention in `custodian/exceptions.py` (subclass `CustodianError`, not bare `Exception`/`KeyError`).
- This repo (`/mnt/homes/galileo/argo/Development/hermes-hackathon-2026`) has another agent session committing to it concurrently. Run `git status` and `git pull --rebase` (if behind) immediately before each task's commit step, and commit after every task (not batched) to minimize collision surface.
- Test command: `pytest tests/ -v` (or scope to the new/touched files during a task, e.g. `pytest tests/test_types.py -v`).

---

### Task 1: `ActionRequest` type with `SpendRequest` alias

**Files:**
- Modify: `custodian/types.py:52-69` (the `SpendRequest` dataclass)
- Test: `tests/test_types.py`

**Interfaces:**
- Produces: `custodian.types.ActionRequest` (dataclass) with all existing `SpendRequest` fields plus `resource_type: str = "spend"` and `payload: dict = field(default_factory=dict)`. `custodian.types.SpendRequest` is the same class object (`SpendRequest = ActionRequest`), so `isinstance(x, SpendRequest)` and `SpendRequest(...)` continue to work unchanged everywhere in the codebase.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_types.py` (append to the file, keep existing imports/tests as-is):

```python
def test_action_request_is_spend_request_alias():
    from custodian.types import ActionRequest, SpendRequest
    assert ActionRequest is SpendRequest


def test_action_request_defaults_to_spend_resource_type():
    from custodian.types import ActionRequest
    req = ActionRequest(amount=10.0, description="test")
    assert req.resource_type == "spend"
    assert req.payload == {}


def test_action_request_accepts_resource_type_and_payload():
    from custodian.types import ActionRequest
    req = ActionRequest(
        amount=500.0,
        description="bulk update",
        resource_type="db_write",
        payload={"table": "users", "rows_affected": 500},
    )
    assert req.resource_type == "db_write"
    assert req.payload == {"table": "users", "rows_affected": 500}


def test_existing_spend_request_construction_unaffected():
    from custodian.types import SpendRequest
    req = SpendRequest(amount=10.0, description="charge", to="acct_123")
    assert req.amount == 10.0
    assert req.to == "acct_123"
    assert req.resource_type == "spend"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_types.py -v -k "action_request"`
Expected: FAIL with `ImportError: cannot import name 'ActionRequest'`

- [ ] **Step 3: Rename `SpendRequest` to `ActionRequest`, add fields, alias back**

In `custodian/types.py`, replace the existing `SpendRequest` dataclass (lines 52-69) with:

```python
@dataclass
class ActionRequest:
    """A request to perform a governed action, before any policy decision
    is made. `amount` is the numeric cost the evaluator compares against
    band caps — for resource_type="spend" it's dollars; for other resource
    types it's whatever unit that resource type's cost function produces
    (rows, blast-radius points, etc.)."""
    amount: float
    description: str
    resource_type: str = "spend"
    payload: dict = field(default_factory=dict)
    recipe: Optional[str] = None
    to: Optional[str] = None
    message: Optional[str] = None
    # Opt-in fields for the new policy directives (Feature 2 margin gate,
    # Feature 3 autorank, Feature 4 self-dealing). All default to None
    # so existing tests that build SpendRequest without them are
    # completely unaffected — and the evaluator only consults these
    # fields when the corresponding directive is set on the policy.
    revenue: Optional[float] = None
    cost: Optional[float] = None
    requester_agent_id: Optional[str] = None
    recipient_agent_id: Optional[str] = None
    requested_at: float = field(default_factory=time.time)


# Backward-compat alias: SpendRequest is ActionRequest, the same class
# object, not a subclass. Every existing `SpendRequest(...)` construction
# and `isinstance(x, SpendRequest)` check continues to work unchanged.
SpendRequest = ActionRequest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_types.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Run the full suite to confirm zero regressions**

Run: `pytest tests/ -v`
Expected: PASS, same pass count as before this task (this is a pure rename + additive-fields change)

- [ ] **Step 6: Commit**

```bash
git status
git add custodian/types.py tests/test_types.py
git commit -m "feat(types): add ActionRequest with resource_type/payload, alias SpendRequest"
```

---

### Task 2: Typed exception for unregistered resource types

**Files:**
- Modify: `custodian/exceptions.py`
- Test: `tests/test_exceptions.py` (create if it doesn't exist; check first)

**Interfaces:**
- Produces: `custodian.exceptions.UnknownResourceTypeError(CustodianError)`

- [ ] **Step 1: Check whether `tests/test_exceptions.py` exists**

Run: `ls tests/test_exceptions.py`

If it exists, read it first and append the new test class in the same style. If it doesn't exist, create it fresh with the content in Step 1 below (it will be the only test class in the file, no existing tests to preserve).

- [ ] **Step 2: Write the failing test**

`tests/test_exceptions.py` (new file, or appended if one exists):

```python
"""Tests for custodian.exceptions."""
from custodian.exceptions import CustodianError, UnknownResourceTypeError


def test_unknown_resource_type_error_is_custodian_error():
    assert issubclass(UnknownResourceTypeError, CustodianError)


def test_unknown_resource_type_error_raisable_with_message():
    try:
        raise UnknownResourceTypeError("unknown resource_type 'db_write'")
    except CustodianError as e:
        assert "db_write" in str(e)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_exceptions.py -v`
Expected: FAIL with `ImportError: cannot import name 'UnknownResourceTypeError'`

- [ ] **Step 4: Add the exception**

Append to `custodian/exceptions.py`:

```python


class UnknownResourceTypeError(CustodianError):
    """@govern or CustodianMiddleware was given a resource_type with no
    registered cost function in custodian.resources.registry."""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_exceptions.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git status
git add custodian/exceptions.py tests/test_exceptions.py
git commit -m "feat(exceptions): add UnknownResourceTypeError"
```

---

### Task 3: Resource-type registry (`custodian/resources/registry.py`)

**Files:**
- Create: `custodian/resources/__init__.py`
- Create: `custodian/resources/registry.py`
- Test: `tests/resources/__init__.py`
- Test: `tests/resources/test_registry.py`

**Interfaces:**
- Consumes: `custodian.exceptions.UnknownResourceTypeError` (Task 2)
- Produces:
  - `custodian.resources.registry.CostFn = Callable[[tuple, dict], float]`
  - `custodian.resources.registry.register(resource_type: str, cost_fn: CostFn) -> None`
  - `custodian.resources.registry.compute_cost(resource_type: str, args: tuple, kwargs: dict) -> float`
  - `custodian.resources.registry.available() -> list[str]`
  - These are re-exported from `custodian.resources` (the package `__init__.py`) for convenience: `custodian.resources.register`, `custodian.resources.compute_cost`, `custodian.resources.available`.
  - Note: `resource_type="spend"` is deliberately **not** registered here. The spend cost path stays inline in `govern.py` (Task 4) to guarantee zero behavior change to the existing, proven spend flow — this registry is only consulted for non-spend resource types.

- [ ] **Step 1: Create the test package directory**

```bash
mkdir -p tests/resources
touch tests/resources/__init__.py
```

- [ ] **Step 2: Write the failing test**

`tests/resources/test_registry.py`:

```python
"""Tests for custodian.resources.registry."""
import pytest

from custodian.exceptions import UnknownResourceTypeError
from custodian.resources import registry


def test_register_and_compute_cost():
    def fixed_cost(args, kwargs):
        return 42.0

    registry.register("test_fixed", fixed_cost)
    try:
        assert registry.compute_cost("test_fixed", (), {}) == 42.0
    finally:
        registry._REGISTRY.pop("test_fixed", None)


def test_compute_cost_passes_args_and_kwargs_through():
    def echo_cost(args, kwargs):
        return float(kwargs.get("rows_affected", 0)) * 2

    registry.register("test_echo", echo_cost)
    try:
        assert registry.compute_cost("test_echo", (), {"rows_affected": 10}) == 20.0
    finally:
        registry._REGISTRY.pop("test_echo", None)


def test_compute_cost_unknown_resource_type_raises():
    with pytest.raises(UnknownResourceTypeError):
        registry.compute_cost("nonexistent_resource_type", (), {})


def test_spend_is_not_pre_registered():
    # "spend" is handled inline in govern.py, not via this registry —
    # see Task 4 rationale.
    assert "spend" not in registry.available()


def test_available_lists_registered_types():
    def noop_cost(args, kwargs):
        return 0.0

    registry.register("test_listed", noop_cost)
    try:
        assert "test_listed" in registry.available()
    finally:
        registry._REGISTRY.pop("test_listed", None)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/resources/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'custodian.resources'`

- [ ] **Step 4: Implement the registry**

`custodian/resources/registry.py`:

```python
"""Resource-type cost registry: the proof that @govern isn't only for
dollars. Each entry binds a resource_type name to a cost function that
turns the governed call's (args, kwargs) into the numeric cost the kernel
compares against band caps. Adding a new governable resource is one
register() call plus a policy.yaml resource_bands entry — no change to
govern.py, middleware.py, or the evaluator.

Mirrors the plugin pattern already used by custodian/packs/registry.py.
"""
from __future__ import annotations

from typing import Callable

from custodian.exceptions import UnknownResourceTypeError

CostFn = Callable[[tuple, dict], float]

_REGISTRY: dict[str, CostFn] = {}


def register(resource_type: str, cost_fn: CostFn) -> None:
    _REGISTRY[resource_type] = cost_fn


def compute_cost(resource_type: str, args: tuple, kwargs: dict) -> float:
    if resource_type not in _REGISTRY:
        raise UnknownResourceTypeError(
            f"unknown resource_type '{resource_type}'. Registered: "
            f"{', '.join(available()) or '(none)'}"
        )
    return _REGISTRY[resource_type](args, kwargs)


def available() -> list[str]:
    return sorted(_REGISTRY)
```

`custodian/resources/__init__.py`:

```python
"""Resource-type registry for governing actions beyond dollar spend.

Built-in resource types register themselves here on import:
  - db_write        (custodian.resources.db_write)
  - browser_action   (custodian.resources.browser_action)

Third parties add their own with:
    from custodian.resources import register
    register("my_resource_type", my_cost_fn)
"""
from custodian.resources.registry import register, compute_cost, available

__all__ = ["register", "compute_cost", "available"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/resources/test_registry.py -v`
Expected: PASS

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions

- [ ] **Step 7: Commit**

```bash
git status
git add custodian/resources/__init__.py custodian/resources/registry.py tests/resources/
git commit -m "feat(resources): add resource-type cost function registry"
```

---

### Task 4: Wire `@govern` to support `resource_type`

**Files:**
- Modify: `custodian/govern.py:54-144` (the `govern()` decorator)
- Test: `tests/test_govern.py`

**Interfaces:**
- Consumes: `custodian.resources.registry.compute_cost` (Task 3), `custodian.types.ActionRequest` (Task 1)
- Produces: `govern(band, cap, description, cost_usd, policy_path, state_dir, verify_output, raise_on_escalation, resource_type="spend")` — new keyword-only-by-convention param `resource_type`, default `"spend"` preserves 100% of existing behavior for every current caller (none of which pass `resource_type`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_govern.py`:

```python
def test_govern_resource_type_defaults_to_spend():
    @govern(band="L2", cap=50.00)
    def charge(amount: float) -> dict:
        return {"ok": True}

    result = charge(amount=10.00)
    assert result.ok
    assert result.amount == 10.00


def test_govern_non_spend_resource_type_uses_registry():
    from custodian.resources import registry

    def rows_cost(args, kwargs):
        return float(kwargs.get("rows_affected", 0)) * 1.0

    registry.register("test_db_write", rows_cost)
    try:
        @govern(band="L2", cap=1000.0, resource_type="test_db_write")
        def bulk_update(table: str, rows_affected: int) -> dict:
            return {"table": table, "updated": rows_affected}

        result = bulk_update(table="users", rows_affected=500)
        assert result.ok
        assert result.amount == 500.0
        assert result.verdict == "autonomous"
    finally:
        registry._REGISTRY.pop("test_db_write", None)


def test_govern_non_spend_resource_type_escalates_over_cap():
    from custodian.resources import registry

    def rows_cost(args, kwargs):
        return float(kwargs.get("rows_affected", 0)) * 1.0

    registry.register("test_db_write_escalate", rows_cost)
    try:
        @govern(band="L2", cap=100.0, resource_type="test_db_write_escalate")
        def bulk_update(table: str, rows_affected: int) -> dict:
            return {"table": table, "updated": rows_affected}

        with pytest.raises(EscalationRequired):
            bulk_update(table="users", rows_affected=5000)
    finally:
        registry._REGISTRY.pop("test_db_write_escalate", None)


def test_govern_unknown_resource_type_raises_unknown_resource_type_error():
    from custodian.exceptions import UnknownResourceTypeError

    @govern(band="L2", cap=100.0, resource_type="totally_unregistered")
    def do_thing() -> dict:
        return {}

    with pytest.raises(UnknownResourceTypeError):
        do_thing()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_govern.py -v -k "resource_type"`
Expected: FAIL — `test_govern_resource_type_defaults_to_spend` passes already (no code change needed for it, it's a regression guard), the other three FAIL with `TypeError: govern() got an unexpected keyword argument 'resource_type'`

- [ ] **Step 3: Implement `resource_type` support**

In `custodian/govern.py`, modify the `govern()` signature and `wrapper()` body. Replace lines 54-97 (from `def govern(` through the `decision = _evaluate(...)` line) with:

```python
def govern(
    band: str = "L2",
    cap: float = 10.00,
    description: Optional[str] = None,
    cost_usd: float = 0.0,
    policy_path: Optional[str] = None,
    state_dir: Optional[str] = None,
    verify_output: bool = False,
    raise_on_escalation: bool = True,
    resource_type: str = "spend",
):
    """
    Decorator that wraps any callable with kernel authority enforcement.

    Usage:
        @govern(band="L2", cap=50.00)
        def charge_customer(amount: float, customer_id: str) -> dict:
            return stripe_client.charge(amount=amount, customer=customer_id)

        result = charge_customer(85.00, "cus_123")
        # result.ok == True if within band
        # raises EscalationRequired if amount > cap
        # raises KernelDenied if kill switch is engaged

    The caller never invokes the kernel explicitly.
    The kernel is the call path.

    resource_type: defaults to "spend" (dollar amount, extracted from the
    call the same way this decorator always has). Pass any other string to
    govern a non-spend action — the cost is computed by whatever function
    is registered for that resource_type in custodian.resources.registry,
    and band caps are read from the policy's `resource_bands.<resource_type>`
    block instead of the top-level `bands` block. See docs/RESOURCE_TYPES.md.
    """
    def decorator(fn: Callable) -> Callable:
        _desc = description or fn.__doc__ or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> GovernedResult:
            if resource_type == "spend":
                # Unchanged from pre-resource_type behavior: extract amount
                # from kwargs first, then first positive numeric positional arg.
                amount = float(kwargs.get("amount", cost_usd))
                if amount == 0.0 and args:
                    for arg in args:
                        if isinstance(arg, (int, float)) and arg > 0:
                            amount = float(arg)
                            break
            else:
                from custodian.resources.registry import compute_cost
                amount = compute_cost(resource_type, args, kwargs)

            request = SpendRequest(
                amount=amount, description=_desc,
                resource_type=resource_type, payload=dict(kwargs),
            )
            audit_id = str(uuid.uuid4())[:8]

            # Load policy + state lazily (not at decoration time)
            decision = _evaluate(request, band, cap, policy_path, state_dir, resource_type)
```

Then, further down in the same `wrapper` function, the existing body (lines 99-137 of the original file: the `if decision.verdict == Verdict.DENIED:` block through the `return result` at the end) is unchanged — leave it exactly as-is, it already just reads `decision`, `amount`, `_desc`, `fn.__name__`.

Now update `_evaluate()` (originally lines 147-195) to accept and thread through `resource_type`:

```python
def _evaluate(request, band, cap, policy_path, state_dir, resource_type="spend"):
    """Internal: load policy/state and call decide(). Never raises."""
    from custodian.policy import load_policy
    from custodian.policy.evaluator import decide
    from custodian.config import CustodianConfig
    from custodian.types import AuthorityState
    import json
    from pathlib import Path

    cfg = CustodianConfig.from_env()

    if policy_path:
        _policy_path = Path(policy_path)
        try:
            policy = load_policy(_policy_path)
        except Exception:
            policy = _minimal_policy(band, cap)
    elif cfg.policy_path and Path(cfg.policy_path).exists():
        try:
            policy = load_policy(Path(cfg.policy_path))
        except Exception:
            policy = _minimal_policy(band, cap)
    else:
        policy = _minimal_policy(band, cap)

    _state_dir = Path(state_dir) if state_dir else cfg.state_dir
    state_file = _state_dir / "authority.json"
    if state_file.exists():
        try:
            state = AuthorityState.from_dict(json.loads(state_file.read_text()))
        except Exception:
            state = AuthorityState(band=Band(band), per_action_cap=cap, session_cap=cap * 10)
    else:
        state = AuthorityState(band=Band(band), per_action_cap=cap, session_cap=cap * 10)

    killed = False
    ks_file = _state_dir / "kill_switch.json"
    if ks_file.exists():
        try:
            killed = bool(json.loads(ks_file.read_text()).get("killed", False))
        except Exception:
            killed = True

    return decide(request, state, policy, killed=killed)
```

(The only change here versus the original is the new `resource_type="spend"` parameter — the body is otherwise byte-for-byte identical. `resource_type` doesn't need to be used inside `_evaluate` itself: it already travels on `request.resource_type`, which `decide()` will read in Task 5. It's accepted as a parameter here only so callers — including Task 6's middleware — have a consistent call signature; it is not currently read inside this function body.)

Note: `CustodianMiddleware.__call__` (Task 6) also calls `_evaluate(...)` positionally — verify that call site after this change (Task 6 covers updating it).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_govern.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions (spend path is untouched logic, just moved inside an `if resource_type == "spend":` guard)

- [ ] **Step 6: Commit**

```bash
git status
git add custodian/govern.py tests/test_govern.py
git commit -m "feat(govern): add resource_type param, route non-spend costs through registry"
```

---

### Task 5: Resource-scoped policy bands (`resource_bands:`)

**Files:**
- Modify: `custodian/policy/schema.py` (the `Policy` dataclass)
- Modify: `custodian/policy/loader.py` (`parse_policy`)
- Modify: `custodian/policy/evaluator.py:47-48` (the `band_cfg` lookup)
- Test: `tests/test_policy_resource_bands.py`

**Interfaces:**
- Consumes: `custodian.types.ActionRequest.resource_type` (Task 1)
- Produces: `Policy.resource_bands: dict[str, dict[Band, BandConfig]]`, `Policy.band_config_for(band: Band, resource_type: str = "spend") -> Optional[BandConfig]`

- [ ] **Step 1: Write the failing test**

`tests/test_policy_resource_bands.py`:

```python
"""Tests for resource-scoped policy bands (resource_bands:)."""
import pytest

from custodian.policy.loader import parse_policy
from custodian.policy.schema import BandConfig, Policy
from custodian.types import Band, ActionRequest, AuthorityState, Verdict
from custodian.policy.evaluator import decide


MINIMAL_SPEND_ONLY = {
    "version": "1.0",
    "default_band": "L2",
    "bands": {
        "L0": {"max_spend": 0},
        "L2": {"max_spend": 50.0},
    },
}

WITH_RESOURCE_BANDS = {
    "version": "1.0",
    "default_band": "L2",
    "bands": {
        "L0": {"max_spend": 0},
        "L2": {"max_spend": 50.0},
    },
    "resource_bands": {
        "db_write": {
            "L2": {"max_spend": 500},
        },
    },
}


def test_policy_without_resource_bands_defaults_empty():
    policy = parse_policy(MINIMAL_SPEND_ONLY)
    assert policy.resource_bands == {}


def test_policy_parses_resource_bands_block():
    policy = parse_policy(WITH_RESOURCE_BANDS)
    assert "db_write" in policy.resource_bands
    assert Band.L2 in policy.resource_bands["db_write"]
    assert policy.resource_bands["db_write"][Band.L2].max_spend == 500.0


def test_band_config_for_spend_reads_top_level_bands():
    policy = parse_policy(WITH_RESOURCE_BANDS)
    cfg = policy.band_config_for(Band.L2, "spend")
    assert cfg is policy.bands[Band.L2]
    assert cfg.max_spend == 50.0


def test_band_config_for_resource_type_reads_resource_bands():
    policy = parse_policy(WITH_RESOURCE_BANDS)
    cfg = policy.band_config_for(Band.L2, "db_write")
    assert cfg.max_spend == 500.0


def test_band_config_for_unconfigured_resource_type_returns_none():
    policy = parse_policy(WITH_RESOURCE_BANDS)
    assert policy.band_config_for(Band.L2, "infra_change") is None


def test_decide_fails_closed_for_unconfigured_resource_type():
    policy = parse_policy(WITH_RESOURCE_BANDS)
    state = AuthorityState(band=Band.L2, per_action_cap=50.0, session_cap=500.0)
    request = ActionRequest(
        amount=10.0, description="test", resource_type="infra_change",
    )
    decision = decide(request, state, policy)
    assert decision.verdict == Verdict.ESCALATION_REQUIRED
    assert "no band configuration" in decision.reason


def test_decide_uses_resource_bands_cap_for_db_write():
    policy = parse_policy(WITH_RESOURCE_BANDS)
    state = AuthorityState(band=Band.L2, per_action_cap=500.0, session_cap=5000.0)
    within_cap = ActionRequest(
        amount=100.0, description="update 100 rows", resource_type="db_write",
    )
    decision = decide(within_cap, state, policy)
    assert decision.verdict == Verdict.AUTONOMOUS

    over_cap = ActionRequest(
        amount=1000.0, description="update 1000 rows", resource_type="db_write",
    )
    decision = decide(over_cap, state, policy)
    assert decision.verdict == Verdict.ESCALATION_REQUIRED


def test_decide_spend_path_unaffected_by_resource_bands_presence():
    # A plain SpendRequest (resource_type="spend" by default) must behave
    # identically whether or not the policy has a resource_bands block.
    policy = parse_policy(WITH_RESOURCE_BANDS)
    state = AuthorityState(band=Band.L2, per_action_cap=50.0, session_cap=500.0)
    request = ActionRequest(amount=10.0, description="charge")
    decision = decide(request, state, policy)
    assert decision.verdict == Verdict.AUTONOMOUS
    assert decision.band == Band.L2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_policy_resource_bands.py -v`
Expected: FAIL — `parse_policy` raises no error on the unknown `resource_bands` key today (it's silently ignored since `parse_policy` only reads keys it knows about), so `policy.resource_bands` raises `AttributeError: 'Policy' object has no attribute 'resource_bands'`, and `policy.band_config_for` raises `AttributeError: 'Policy' object has no attribute 'band_config_for'`.

- [ ] **Step 3: Add `resource_bands` field and `band_config_for()` to `Policy`**

In `custodian/policy/schema.py`, modify the `Policy` dataclass (originally lines 160-172):

```python
@dataclass
class Policy:
    version: str
    default_band: Band
    bands: dict[Band, BandConfig]
    rules: list[Rule] = field(default_factory=list)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    # Opt-in policy-level directives. The defaults preserve full backward
    # compatibility: a Policy() constructed without these never invokes the
    # new checks. `margins=None` is the sentinel that check_margin() looks
    # for; same for `policies=None` in check_self_dealing().
    margins: Optional[MarginsConfig] = None
    policies: Optional[PoliciesConfig] = None
    # Opt-in: band caps for non-"spend" resource types (db_write,
    # infra_change, browser_action, ...). Empty dict means "no non-spend
    # resource type is governed by this policy" — band_config_for() then
    # returns None for any resource_type other than "spend", and the
    # evaluator fails closed (ESCALATION_REQUIRED) rather than silently
    # falling back to the dollar-denominated `bands` map, which would be a
    # unit-confusion bug (comparing e.g. rows_affected against a dollar cap).
    resource_bands: dict[str, dict[Band, BandConfig]] = field(default_factory=dict)

    def band_config_for(self, band: Band, resource_type: str = "spend") -> Optional[BandConfig]:
        if resource_type == "spend":
            return self.bands.get(band)
        return self.resource_bands.get(resource_type, {}).get(band)
```

Then, in `Policy.validate()` (originally lines 174-200), add a loop validating the resource-scoped band configs. Insert this right after the existing `for band_cfg in self.bands.values(): band_cfg.validate()` loop:

```python
        for band_cfg in self.bands.values():
            band_cfg.validate()
        for resource_type, band_map in self.resource_bands.items():
            for band_cfg in band_map.values():
                band_cfg.validate()
        for rule in self.rules:
```

(This slots between the existing `band_cfg.validate()` loop and the existing `for rule in self.rules:` loop — the rest of `validate()` is unchanged.)

- [ ] **Step 4: Parse `resource_bands:` in the YAML loader**

In `custodian/policy/loader.py`, modify `parse_policy()` (originally lines 92-158). Right after the existing top-level `bands` parsing block:

```python
    bands = {}
    for name, band_raw in raw["bands"].items():
        cfg = _parse_band(band_raw or {}, name)
        bands[cfg.name] = cfg
```

add:

```python
    resource_bands_raw = raw.get("resource_bands", {})
    if not isinstance(resource_bands_raw, dict):
        raise PolicyValidationError("'resource_bands' must be a mapping")
    resource_bands: dict[str, dict[Band, BandConfig]] = {}
    for resource_type, bands_for_type_raw in resource_bands_raw.items():
        if not isinstance(bands_for_type_raw, dict):
            raise PolicyValidationError(
                f"resource_bands.{resource_type} must be a mapping"
            )
        resource_bands[resource_type] = {}
        for name, band_raw in bands_for_type_raw.items():
            cfg = _parse_band(band_raw or {}, name)
            resource_bands[resource_type][cfg.name] = cfg
```

Then pass it into the `Policy(...)` construction at the end of `parse_policy()` (originally lines 141-150):

```python
    policy = Policy(
        version=str(raw["version"]),
        default_band=default_band,
        bands=bands,
        rules=rules,
        escalation=escalation,
        margins=margins,
        policies=policies,
        resource_bands=resource_bands,
    )
    policy.validate()
    return policy
```

- [ ] **Step 5: Use `band_config_for()` in the evaluator**

In `custodian/policy/evaluator.py`, change line 48 from:

```python
    band_cfg = policy.bands.get(band)
```

to:

```python
    band_cfg = policy.band_config_for(band, request.resource_type)
```

This is the only line changed in `evaluator.py`. Every other line in `decide()` — kill switch check, autorank, envelope, margin, self-dealing, cap comparisons, the final `Decision` construction — is untouched. `request.resource_type` defaults to `"spend"` (Task 1), so any caller that constructs a `SpendRequest`/`ActionRequest` without setting `resource_type` gets `policy.bands.get(band)`, identical to today.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_policy_resource_bands.py -v`
Expected: PASS

- [ ] **Step 7: Run full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git status
git add custodian/policy/schema.py custodian/policy/loader.py custodian/policy/evaluator.py tests/test_policy_resource_bands.py
git commit -m "feat(policy): add resource_bands: block for non-spend band caps"
```

---

### Task 6: `CustodianMiddleware` supports `resource_type`

**Files:**
- Modify: `custodian/middleware.py`
- Test: `tests/test_middleware.py`

**Interfaces:**
- Consumes: `_evaluate(request, band, cap, policy_path, state_dir, resource_type)` (Task 4), `custodian.resources.registry.compute_cost` (Task 3)
- Produces: `CustodianMiddleware.register_path(path, band="L2", cap=10.00, resource_type="spend")`

- [ ] **Step 1: Write the failing test**

First check the existing `tests/test_middleware.py` for its test harness pattern (how it constructs an ASGI scope/receive/send and calls the middleware) — reuse that exact pattern for the new tests rather than inventing a new one. Read the file, then append tests structured the same way as its existing tests, covering:

```python
def test_register_path_defaults_resource_type_to_spend():
    from custodian.middleware import CustodianMiddleware

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    middleware = CustodianMiddleware(app)
    middleware.register_path("/charge", band="L2", cap=50.00)
    assert middleware._governed_paths["/charge"]["resource_type"] == "spend"


def test_register_path_accepts_resource_type():
    from custodian.middleware import CustodianMiddleware

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    middleware = CustodianMiddleware(app)
    middleware.register_path("/db/write", band="L2", cap=500.0, resource_type="db_write")
    assert middleware._governed_paths["/db/write"]["resource_type"] == "db_write"
```

(If `tests/test_middleware.py` uses async test helpers like `pytest.mark.asyncio` or a local `run_asgi()` helper for full request/response tests, add one additional async test in that same style that POSTs a `db_write` payload — e.g. `{"rows_affected": 10}` — through a registered `/db/write` path with a `test_db_write` resource type registered via `custodian.resources.registry.register`, and asserts the response passes through (autonomous) for a low row count and gets a 402 for a high row count. Match whatever async pattern the existing file already uses; do not introduce a new one.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_middleware.py -v -k "resource_type"`
Expected: FAIL with `KeyError: 'resource_type'` (the dict from `register_path` doesn't have that key yet)

- [ ] **Step 3: Implement `resource_type` in `CustodianMiddleware`**

In `custodian/middleware.py`, modify `register_path` (originally lines 38-41):

```python
    def register_path(self, path: str, band: str = "L2", cap: float = 10.00,
                       resource_type: str = "spend"):
        """Register a route as governed. Returns self for chaining."""
        self._governed_paths[path] = {"band": band, "cap": cap, "resource_type": resource_type}
        return self
```

Then modify `__call__` (originally lines 43-109). Replace the cost-extraction block (originally lines 55-67):

```python
        # Buffer body — needed to extract amount AND replay to the app
        body = b""
        more_body = True
        while more_body:
            msg = await receive()
            body += msg.get("body", b"")
            more_body = msg.get("more_body", False)

        amount = 0.0
        try:
            amount = float(json.loads(body).get("amount", 0.0))
        except Exception:
            pass
```

with:

```python
        # Buffer body — needed to extract cost AND replay to the app
        body = b""
        more_body = True
        while more_body:
            msg = await receive()
            body += msg.get("body", b"")
            more_body = msg.get("more_body", False)

        resource_type = route_cfg["resource_type"]
        amount = 0.0
        try:
            body_json = json.loads(body)
            if resource_type == "spend":
                amount = float(body_json.get("amount", 0.0))
            else:
                from custodian.resources.registry import compute_cost
                amount = compute_cost(resource_type, (), body_json)
        except Exception:
            pass
```

Then update the `SpendRequest(...)` construction and `_evaluate(...)` call (originally lines 69-74):

```python
        from custodian.govern import _evaluate
        from custodian.types import SpendRequest, Verdict

        request = SpendRequest(
            amount=amount, description=f"HTTP {path}",
            resource_type=resource_type, payload=body_json if isinstance(body, bytes) and body else {},
        )
        decision = _evaluate(request, route_cfg["band"], route_cfg["cap"],
                             self.policy_path, self.state_dir, resource_type)
```

Note: `body_json` may be undefined if the `try/except` above hit the exception branch before assigning it (e.g. malformed JSON). Guard against that directly instead — replace the line above with a safer version:

```python
        from custodian.govern import _evaluate
        from custodian.types import SpendRequest, Verdict

        request = SpendRequest(
            amount=amount, description=f"HTTP {path}",
            resource_type=resource_type,
        )
        decision = _evaluate(request, route_cfg["band"], route_cfg["cap"],
                             self.policy_path, self.state_dir, resource_type)
```

(Dropping `payload=` here — the middleware's `payload` isn't consumed by anything yet since receipts/audit don't read it in this plan's scope; keep the change minimal. `body_json` is already read safely inside the earlier `try/except` for cost computation.)

The rest of `__call__` (the `if decision.verdict in (...)` branch through the end) is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_middleware.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git status
git add custodian/middleware.py tests/test_middleware.py
git commit -m "feat(middleware): support resource_type on governed routes"
```

---

### Task 7: Reference resource type — `db_write`

**Files:**
- Create: `custodian/resources/db_write.py`
- Create: `custodian/resources/db_write_policy.yaml`
- Test: `tests/resources/test_db_write.py`

**Interfaces:**
- Consumes: `custodian.resources.registry.register` (Task 3), `custodian.govern.govern(resource_type=...)` (Task 4)
- Produces: `custodian.resources.db_write.SENSITIVITY_WEIGHTS: dict[str, float]`, `custodian.resources.db_write.db_write_cost(args: tuple, kwargs: dict) -> float` (registered under `"db_write"` on import of `custodian.resources`)

This is the proof-of-concept resource type: cost = `rows_affected * table_sensitivity_weight`. A write to a low-sensitivity table (e.g. `page_views`) costs less per row than a write to a high-sensitivity table (e.g. `users` or `payments`).

- [ ] **Step 1: Write the failing test**

`tests/resources/test_db_write.py`:

```python
"""Tests for the db_write reference resource type."""
import pytest

from custodian import govern, EscalationRequired
from custodian.resources import registry
from custodian.resources.db_write import SENSITIVITY_WEIGHTS, db_write_cost


def test_db_write_registered_on_import():
    assert "db_write" in registry.available()


def test_db_write_cost_scales_with_rows_and_sensitivity():
    low = db_write_cost((), {"table": "page_views", "rows_affected": 100})
    high = db_write_cost((), {"table": "users", "rows_affected": 100})
    assert SENSITIVITY_WEIGHTS["users"] > SENSITIVITY_WEIGHTS["page_views"]
    assert high > low


def test_db_write_cost_unknown_table_uses_default_weight():
    cost = db_write_cost((), {"table": "some_new_table", "rows_affected": 10})
    assert cost == 10 * SENSITIVITY_WEIGHTS["_default"]


def test_governed_db_write_autonomous_under_cap():
    @govern(band="L2", cap=1000.0, resource_type="db_write")
    def bulk_update(table: str, rows_affected: int) -> dict:
        return {"table": table, "updated": rows_affected}

    result = bulk_update(table="page_views", rows_affected=50)
    assert result.ok
    assert result.verdict == "autonomous"


def test_governed_db_write_escalates_for_sensitive_table():
    @govern(band="L2", cap=100.0, resource_type="db_write")
    def bulk_update(table: str, rows_affected: int) -> dict:
        return {"table": table, "updated": rows_affected}

    with pytest.raises(EscalationRequired):
        bulk_update(table="users", rows_affected=1000)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/resources/test_db_write.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'custodian.resources.db_write'`

- [ ] **Step 3: Implement the `db_write` resource type**

`custodian/resources/db_write.py`:

```python
"""Reference resource type: governing bulk database writes by row count and
table sensitivity, instead of dollars. This is the proof that the
resource-type registry (custodian.resources.registry) generalizes beyond
spend — same @govern decorator, same bands, same kill switch, same
receipts, different cost unit.

Cost = rows_affected * SENSITIVITY_WEIGHTS[table] (or "_default" for tables
not explicitly weighted). A write to `users` costs more per row than a
write to `page_views`, so the same band cap (e.g. L2 = 500) permits a much
larger page_views write than a users write.
"""
from __future__ import annotations

SENSITIVITY_WEIGHTS: dict[str, float] = {
    "users": 5.0,
    "payments": 10.0,
    "page_views": 0.1,
    "_default": 1.0,
}


def db_write_cost(args: tuple, kwargs: dict) -> float:
    table = kwargs.get("table", "_default")
    rows_affected = float(kwargs.get("rows_affected", 0))
    weight = SENSITIVITY_WEIGHTS.get(table, SENSITIVITY_WEIGHTS["_default"])
    return rows_affected * weight


from custodian.resources.registry import register  # noqa: E402
register("db_write", db_write_cost)
```

`custodian/resources/db_write_policy.yaml` (example policy fragment — documents the resource_bands shape for this resource type, referenced from `docs/RESOURCE_TYPES.md` in Task 8, not loaded automatically):

```yaml
# Example resource_bands fragment for db_write. Merge this under the
# top-level `resource_bands:` key of your policy.yaml — see
# docs/RESOURCE_TYPES.md for the full policy.yaml shape.
resource_bands:
  db_write:
    L0:
      max_spend: 0
      requires_approval: true
      approval_backend: twilio_verify
    L2:
      max_spend: 500
      requires_approval: false
    L4:
      max_spend: null
      requires_approval: true
      approval_backend: twilio_verify
```

Now update `custodian/resources/__init__.py` (from Task 3) to import `db_write` so its `register()` call runs on package import:

```python
"""Resource-type registry for governing actions beyond dollar spend.

Built-in resource types register themselves here on import:
  - db_write        (custodian.resources.db_write)

Third parties add their own with:
    from custodian.resources import register
    register("my_resource_type", my_cost_fn)
"""
from custodian.resources.registry import register, compute_cost, available
from custodian.resources import db_write  # noqa: F401  (registers "db_write" on import)

__all__ = ["register", "compute_cost", "available"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/resources/test_db_write.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git status
git add custodian/resources/db_write.py custodian/resources/db_write_policy.yaml custodian/resources/__init__.py tests/resources/test_db_write.py
git commit -m "feat(resources): add db_write reference resource type"
```

---

### Task 8: Second resource type — `browser_action` — proves the pattern generalizes

**Files:**
- Create: `custodian/resources/browser_action.py`
- Create: `custodian/resources/browser_action_policy.yaml`
- Test: `tests/resources/test_browser_action.py`
- Modify: `custodian/resources/__init__.py`

**Interfaces:**
- Consumes: `custodian.resources.registry.register` (Task 3)
- Produces: `custodian.resources.browser_action.ACTION_RISK: dict[str, float]`, `custodian.resources.browser_action.browser_action_cost(args: tuple, kwargs: dict) -> float` (registered under `"browser_action"`)

This is a deliberately different cost shape than `db_write` (a lookup table keyed by action name, not a multiplication) — the point of this task is to confirm the registry pattern doesn't secretly assume "rows * weight" is the only shape a `CostFn` can take.

- [ ] **Step 1: Write the failing test**

`tests/resources/test_browser_action.py`:

```python
"""Tests for the browser_action resource type — confirms the registry
pattern generalizes beyond db_write's multiplicative cost shape."""
import pytest

from custodian import govern, EscalationRequired
from custodian.resources import registry
from custodian.resources.browser_action import ACTION_RISK, browser_action_cost


def test_browser_action_registered_on_import():
    assert "browser_action" in registry.available()


def test_browser_action_cost_read_is_low_risk():
    cost = browser_action_cost((), {"action": "click"})
    assert cost == ACTION_RISK["click"]
    assert cost < ACTION_RISK["submit_form"]


def test_browser_action_cost_unknown_action_uses_default_risk():
    cost = browser_action_cost((), {"action": "invoke_unknown_widget"})
    assert cost == ACTION_RISK["_default"]


def test_governed_browser_action_autonomous_for_click():
    @govern(band="L2", cap=10.0, resource_type="browser_action")
    def perform(action: str, selector: str) -> dict:
        return {"action": action, "selector": selector}

    result = perform(action="click", selector="#submit")
    assert result.ok


def test_governed_browser_action_escalates_for_high_risk_action():
    @govern(band="L2", cap=10.0, resource_type="browser_action")
    def perform(action: str, selector: str = "") -> dict:
        return {"action": action}

    with pytest.raises(EscalationRequired):
        perform(action="submit_payment_form", selector="#pay")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/resources/test_browser_action.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'custodian.resources.browser_action'`

- [ ] **Step 3: Implement the `browser_action` resource type**

`custodian/resources/browser_action.py`:

```python
"""Second reference resource type: governing browser automation actions by
a flat per-action-name risk lookup, rather than db_write's rows * weight
multiplication. Confirms custodian.resources.registry's CostFn contract
((args, kwargs) -> float) doesn't secretly assume a multiplicative shape —
any function of the call's args/kwargs is a valid cost function.
"""
from __future__ import annotations

ACTION_RISK: dict[str, float] = {
    "click": 1.0,
    "read": 1.0,
    "scroll": 1.0,
    "submit_form": 25.0,
    "submit_payment_form": 100.0,
    "_default": 50.0,
}


def browser_action_cost(args: tuple, kwargs: dict) -> float:
    action = kwargs.get("action", "_default")
    return ACTION_RISK.get(action, ACTION_RISK["_default"])


from custodian.resources.registry import register  # noqa: E402
register("browser_action", browser_action_cost)
```

`custodian/resources/browser_action_policy.yaml` (example fragment, documented in `docs/RESOURCE_TYPES.md`):

```yaml
resource_bands:
  browser_action:
    L2:
      max_spend: 10
      requires_approval: false
    L4:
      max_spend: null
      requires_approval: true
      approval_backend: twilio_verify
```

Update `custodian/resources/__init__.py` to also import `browser_action`:

```python
"""Resource-type registry for governing actions beyond dollar spend.

Built-in resource types register themselves here on import:
  - db_write        (custodian.resources.db_write)
  - browser_action   (custodian.resources.browser_action)

Third parties add their own with:
    from custodian.resources import register
    register("my_resource_type", my_cost_fn)
"""
from custodian.resources.registry import register, compute_cost, available
from custodian.resources import db_write  # noqa: F401  (registers "db_write" on import)
from custodian.resources import browser_action  # noqa: F401  (registers "browser_action" on import)

__all__ = ["register", "compute_cost", "available"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/resources/test_browser_action.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `pytest tests/ -v`
Expected: PASS, no regressions — this is the final task, so this is also the full-plan regression check.

- [ ] **Step 6: Commit**

```bash
git status
git add custodian/resources/browser_action.py custodian/resources/browser_action_policy.yaml custodian/resources/__init__.py tests/resources/test_browser_action.py
git commit -m "feat(resources): add browser_action resource type, confirms registry pattern generalizes"
```

---

### Task 9: Documentation

**Files:**
- Modify: `docs/POLICY_LANGUAGE.md`
- Create: `docs/RESOURCE_TYPES.md`

**Interfaces:**
- Consumes: nothing new — this task documents the surface built in Tasks 1-8.

- [ ] **Step 1: Read the existing `docs/POLICY_LANGUAGE.md`**

Read the file to match its existing structure/heading style before appending.

- [ ] **Step 2: Add a `resource_bands:` section to `docs/POLICY_LANGUAGE.md`**

Append a new section (matching the file's existing heading level for top-level directives, e.g. `##`):

```markdown
## resource_bands (opt-in — governing non-spend actions)

By default, the `bands:` block governs dollar-denominated spend
(`resource_type="spend"`, the default for `@govern` and
`CustodianMiddleware.register_path`). To govern a different kind of
action — a database write, an infrastructure change, a browser action —
add a `resource_bands:` block:

```yaml
resource_bands:
  db_write:
    L2:
      max_spend: 500        # rows, not dollars — see the resource type's CostFn
      requires_approval: false
```

The band names (`L0`-`L4`) are shared across resource types, but each
resource type's `max_spend` is denominated in whatever unit that
resource type's cost function produces — see
[`docs/RESOURCE_TYPES.md`](RESOURCE_TYPES.md) for the built-in `db_write`
and `browser_action` resource types and how to register your own.

A `resource_type` with no matching entry under `resource_bands:` fails
closed: `@govern(resource_type="infra_change", ...)` on a policy with no
`resource_bands.infra_change` block always escalates, it never falls back
to the dollar-denominated `bands:` block.
```

- [ ] **Step 3: Write `docs/RESOURCE_TYPES.md`**

```markdown
# Resource Types

Custodian's kernel enforcement — bands, caps, the kill switch, receipts —
isn't limited to dollar spend. `@govern` and `CustodianMiddleware` can
govern any action an agent takes, as long as that action has a
`resource_type` with a registered cost function.

## How it works

1. A **cost function** turns a governed call's `(args, kwargs)` into a
   number: `CostFn = Callable[[tuple, dict], float]`.
2. That number is compared against a band cap, exactly like a dollar
   amount is today — same `policy/evaluator.py::decide()` logic, same
   kill switch, same escalation/denial/autonomous verdicts.
3. `policy.yaml` gets a `resource_bands.<resource_type>` block (see
   [`docs/POLICY_LANGUAGE.md`](POLICY_LANGUAGE.md#resource_bands-opt-in--governing-non-spend-actions))
   defining what each band's cap means for that resource type.

## Built-in resource types

### `db_write`

Cost = `rows_affected * table_sensitivity_weight`. See
`custodian/resources/db_write.py` for `SENSITIVITY_WEIGHTS` and
`custodian/resources/db_write_policy.yaml` for an example
`resource_bands` fragment.

```python
from custodian import govern

@govern(band="L2", cap=500.0, resource_type="db_write")
def bulk_update(table: str, rows_affected: int) -> dict:
    return db.execute(f"UPDATE {table} SET ...")
```

### `browser_action`

Cost = a flat per-action-name risk lookup (`ACTION_RISK` in
`custodian/resources/browser_action.py`) — `click`/`read`/`scroll` are
low-risk, `submit_form` and `submit_payment_form` are higher. See
`custodian/resources/browser_action_policy.yaml` for an example
`resource_bands` fragment.

```python
from custodian import govern

@govern(band="L2", cap=10.0, resource_type="browser_action")
def perform(action: str, selector: str) -> dict:
    return browser.perform(action, selector)
```

## Registering your own resource type

```python
from custodian.resources import register

def infra_change_cost(args: tuple, kwargs: dict) -> float:
    blast_radius = {"restart_pod": 1.0, "delete_namespace": 1000.0}
    return blast_radius.get(kwargs.get("change_type"), 50.0)

register("infra_change", infra_change_cost)
```

Then govern a function with it:

```python
@govern(band="L2", cap=100.0, resource_type="infra_change")
def apply_change(change_type: str, target: str) -> dict:
    ...
```

...and add a `resource_bands.infra_change` block to your `policy.yaml`.
A `resource_type` with no registered cost function raises
`custodian.exceptions.UnknownResourceTypeError`. A `resource_type` with a
registered cost function but no matching `resource_bands` entry in the
policy fails closed (`ESCALATION_REQUIRED`, "no band configuration
found").

`CustodianMiddleware.register_path` takes the same `resource_type`
parameter, reading the cost from the governed route's JSON request body
instead of a function call's `(args, kwargs)`.
```

- [ ] **Step 4: Verify the docs render correctly**

Run: `cat docs/RESOURCE_TYPES.md` and visually confirm no broken code fences (this file has nested triple-backtick examples inside a markdown file — check the outer file's own fences aren't accidentally closed early).

- [ ] **Step 5: Commit**

```bash
git status
git add docs/POLICY_LANGUAGE.md docs/RESOURCE_TYPES.md
git commit -m "docs: document resource_bands policy directive and resource type registration"
```

---

## Self-Review Notes

- **Spec coverage:** §1 (`ActionRequest`) → Task 1. §2 (registry) → Task 3, wired into `@govern` in Task 4. §3 (`resource_type` policy scoping) → Task 5. §4 (middleware) → Task 6. §5 (`db_write` reference type) → Task 7. Rollout step 5 (second resource type) → Task 8. Docs → Task 9.
- **Resolved open questions from the spec:**
  - Policy schema for resource-scoped bands: `Policy.resource_bands: dict[str, dict[Band, BandConfig]]`, populated from a top-level `resource_bands:` YAML block (Task 5) — chosen over duplicate-keyed `bands:` entries because `Policy.bands` is `dict[Band, BandConfig]` and Python dicts can't hold two keys named `L2`.
  - Where resource-type packs live: `custodian/resources/<type>.py` + `custodian/resources/<type>_policy.yaml`, parallel to (not merged into) `custodian/packs/`, since packs are business-domain skill bundles (refunds, purchasing, cloud) and resource types are a lower-level kernel concept (what unit a cost is denominated in).
  - Receipt/audit unit labels for non-dollar costs: deliberately deferred, matching the spec — `GovernedReceipt`/`AuditEntry` are untouched in this plan.
  - Second resource type: `browser_action`, chosen specifically because its cost shape (flat lookup) differs from `db_write`'s (multiplicative), to prove the `CostFn` contract doesn't assume one shape.
- **Spend-path safety:** Tasks 1, 3, and 5 are purely additive (new fields/files with backward-compatible defaults). Task 4's only change to the spend path is wrapping the existing extraction code in `if resource_type == "spend":` — the code inside that branch is unmodified. Task 6 mirrors this in the middleware. Every task's Step "Run full suite" is the regression gate for this claim.
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code, not a description of code.
- **Type consistency check:** `CostFn` signature `(args: tuple, kwargs: dict) -> float` is identical across Task 3's registry, Task 4's `govern.py` call site, Task 6's middleware call site, and Tasks 7-8's `db_write_cost`/`browser_action_cost` implementations. `resource_type` parameter name and default (`"spend"`) is identical across `govern()`, `_evaluate()`, `CustodianMiddleware.register_path()`, `Policy.band_config_for()`, and `ActionRequest.resource_type`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-01-pluggable-enforcement-surface.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
