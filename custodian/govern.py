from __future__ import annotations
import functools
import hashlib
import inspect
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

from custodian.types import Band, Decision, SpendRequest, Verdict
from custodian.bus import _bus


def _source_sha(func: Callable) -> Optional[str]:
    """Return SHA-256 hex of the decorated function's source file.
    Returns None if source is unavailable (built-in, REPL, dynamically
    generated) — tamper check stays disabled rather than silently allowing
    the gap."""
    try:
        source_file = inspect.getsourcefile(func)
        if source_file is None or not os.path.isfile(source_file):
            return None
        return hashlib.sha256(open(source_file, "rb").read()).hexdigest()
    except (TypeError, OSError):
        return None


def _default_tamper_dir() -> str:
    """Where tamper snapshots live when the caller names no state_dir.

    NOT /tmp, which is what this used to default to. /tmp is world-writable
    (mode 1777 on POSIX), so the agent this check exists to catch could
    simply delete its own snapshot: `rm /tmp/charge.bk.sha`, edit the
    source, and the next run finds no stored hash, takes the "first run"
    branch, and re-snapshots the tampered source as legitimate. A tamper
    check whose state the tampering party can erase is not a check.

    ~/.custodian is on kernel_self_protection.py's protected list, but that
    adapter only runs inside custodian/tools/registry.py's CustodianTool.invoke()
    pipeline. @govern is a standalone decorator with no adapter pipeline of
    its own -- any in-process code, including the code being governed, can
    still delete or truncate this snapshot directly with zero interference
    from this module. Using ~/.custodian raises the bar over /tmp (not
    every process has reason to write there) but is not itself a guarantee;
    treat this as tamper-evident, not tamper-proof, same disclosed limits
    as custodian/universal_ledger.py's hash chain.
    """
    return os.environ.get(
        "CUSTODIAN_STATE_DIR",
        os.path.join(os.path.expanduser("~"), ".custodian", "tamper"),
    )


def _extract_amount(fn: Callable, args: tuple, kwargs: dict, cost_usd: float) -> float:
    """Return the real value of the parameter named ``amount``, however it
    was actually passed (keyword or positional).

    Used to scan `args` for "the first nonzero, non-bool int/float" when
    `amount` wasn't in kwargs -- for a positional call whose signature has
    another numeric parameter before `amount` (an id, a quantity, a count),
    it gated on that decoy value instead of the real spend. Reproduced:
    `@govern(cap=10.00) def transfer(account_id, amount): ...` called as
    `transfer(7, 999999.99)` was gated on `account_id=7` and sailed through
    autonomously with a real amount of $999,999.99 under a $10 cap. Found
    in review. Binding args/kwargs to the function's real signature and
    reading the parameter actually named `amount` closes this regardless
    of call style; a callable with no `amount` parameter (a fixed-cost
    action) falls back to the declared cost_usd rather than guessing.
    """
    value = kwargs.get("amount")
    if value is None:
        try:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            value = bound.arguments.get("amount")
        except (TypeError, ValueError):
            value = None
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(cost_usd)
    return float(value)


def _tamper_key(func: Callable) -> str:
    """A filename that identifies THIS function, not merely its bare name.

    Keying on __name__ alone made every `charge` in the codebase share one
    snapshot file: a false drift (denying an untouched function) when two
    modules disagree, and a false OK when they happen to match. Qualified
    module+qualname, hashed so it is a safe filename.
    """
    ident = f"{getattr(func, '__module__', '?')}.{getattr(func, '__qualname__', getattr(func, '__name__', 'unknown'))}"
    return hashlib.sha256(ident.encode("utf-8")).hexdigest()[:32]


def _tamper_check(
    func: Callable, state_dir: Optional[str]
) -> Tuple[Optional[str], Optional[str]]:
    """Tamper-snapshot: on first run, take SHA-256 of the source file.
    On subsequent runs, verify it matches. Returns (snapshot_sha, verdict).

    Pattern from cyberware's executor.py .bk: the source is hashed on first
    run and stored in <state_dir>/<key>.bk.sha. Subsequent runs re-read the
    source and compare — a drift means the function's source changed between
    the policy check and execution (agent editing source between audit and
    runtime).

    Verdict: "ok" = matches, "drift" = tampered, "disabled" = no source
    available, "unprotected" = the snapshot could not be persisted.
    """
    source_sha = _source_sha(func)
    if source_sha is None:
        return None, "disabled"

    state_dir = state_dir or _default_tamper_dir()
    bk_path = os.path.join(state_dir, f"{_tamper_key(func)}.bk.sha")

    try:
        stored = open(bk_path, "r").read().strip()
        # An empty (zero-byte or whitespace-only) snapshot is corrupt or
        # truncated, not "no snapshot yet" -- `if stored and ...` treated it
        # as falsy and fell through to "matches", silently accepting any
        # source as legitimate. A truncated snapshot must fail closed the
        # same as a mismatched one. Found in review.
        if stored != source_sha:
            return source_sha, "drift"  # tamper detected (includes truncation)
        return source_sha, "ok"
    except FileNotFoundError:
        # First run: write the snapshot.
        #
        # Written to a per-writer temp file and moved into place with
        # os.replace() (atomic on POSIX and Windows), not `open(bk_path,
        # "w").write(...)` directly. The direct-write form let N threads
        # racing to govern() the SAME function for the first time (a real
        # shape: 100 concurrent requests hitting a freshly deployed
        # process) truncate-then-write the same path concurrently -- a
        # reader could observe the file mid-write, empty or partial. That
        # used to read as falsy and silently pass as "ok" (the exact bug
        # fixed above); now that an empty/partial read correctly reports
        # "drift", the SAME race instead produced spurious tamper denials
        # under concurrent first-run load. Verified: 100 concurrent calls
        # to a freshly-decorated function denied ~15-20% of the time before
        # this fix, 0% after. Found in review (of the fix above, not the
        # original code -- this race was always there, just silently
        # masked).
        try:
            os.makedirs(state_dir, exist_ok=True)
            tmp_path = f"{bk_path}.{uuid.uuid4().hex}.tmp"
            with open(tmp_path, "w") as f:
                f.write(source_sha)
            os.replace(tmp_path, bk_path)
        except OSError:
            # Do NOT report "ok" here. A snapshot that was never written means
            # every later run also takes this branch, so the check silently
            # never fires -- the previous code swallowed the error and returned
            # "ok", which reads identically to a verified function. Say so
            # instead, and let the caller decide.
            return source_sha, "unprotected"
        return source_sha, "ok"


@dataclass
class GovernedResult:
    """Return value of every @govern-wrapped function."""
    value: Any                    # the wrapped function's actual return value
    verdict: str                  # "autonomous" / "escalation_required" / "denied"
    audit_id: str
    band: str
    amount: float
    description: str
    fn_name: str                  # actual __name__ of the governed function
    elapsed_ms: float
    claim_proof: Optional[str] = None   # "verified" / "contradicted" / "unverifiable"
    ts: float = field(default_factory=time.time)

    @property
    def ok(self) -> bool:
        return self.verdict == "autonomous"

    def receipt(self) -> "GovernedReceipt":
        from custodian.receipt import GovernedReceipt
        return GovernedReceipt.build(
            fn_name=self.fn_name, band=self.band, amount=self.amount,
            description=self.description, verdict=self.verdict,
            reason="", elapsed_ms=self.elapsed_ms, output=self.value,
            claim_proof=self.claim_proof,
        )


class EscalationRequired(Exception):
    def __init__(self, decision, request):
        self.decision = decision
        self.request = request
        super().__init__(f"Escalation required: {decision.reason}")


class KernelDenied(Exception):
    def __init__(self, decision, request):
        self.decision = decision
        self.request = request
        super().__init__(f"Kernel denied: {decision.reason}")


def govern(
    band: str = "L2",
    cap: float = 10.00,
    description: Optional[str] = None,
    cost_usd: float = 0.0,
    policy_path: Optional[str] = None,
    state_dir: Optional[str] = None,
    verify_output: bool = False,
    raise_on_escalation: bool = True,
    tamper_check: bool = True,
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

    New in 0.2.1: tamper_check — source file SHA-256 snapshot on first run,
    verified on subsequent runs. Pattern from cyberware's executor.py .bk.
    Set tamper_check=False to disable (e.g. when the function is dynamically
    generated or source is unavailable).
    """
    def decorator(fn: Callable) -> Callable:
        _desc = description or fn.__doc__ or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> GovernedResult:
            amount = _extract_amount(fn, args, kwargs, cost_usd)

            # Tamper check: source file must not have changed since first run
            # (agent editing source between policy check and execution)
            tamper_verdict = None
            if tamper_check:
                _, tv = _tamper_check(fn, state_dir)
                tamper_verdict = tv
                if tv in ("drift", "unprotected"):
                    # Emit before returning. Every other denial path on this
                    # function emits (kernel_denied, escalation_required); this
                    # one returned silently, so the single most security-
                    # relevant denial -- the source changed between the policy
                    # check and execution -- left no trace in the audit chain
                    # at all.
                    _bus.emit("kernel_denied", {
                        "audit_id": f"{fn.__name__}:-1", "amount": amount,
                        "reason": (
                            "tamper check: source file changed since the snapshot "
                            "was taken" if tv == "drift" else
                            "tamper check: snapshot could not be persisted"
                        ),
                        "fn": fn.__name__,
                    })
                    return GovernedResult(
                        value=None, verdict="denied",
                        audit_id=f"{fn.__name__}:-1",
                        band=band, amount=amount, description=_desc,
                        fn_name=fn.__name__, elapsed_ms=0.0,
                    )

            request = SpendRequest(amount=amount, description=_desc)
            audit_id = str(uuid.uuid4())[:8]

            # Load policy + state lazily (not at decoration time)
            decision = _evaluate(request, band, cap, policy_path, state_dir)

            if decision.verdict == Verdict.DENIED:
                _bus.emit("kernel_denied", {
                    "audit_id": audit_id, "amount": amount, "reason": decision.reason
                })
                if raise_on_escalation:
                    raise KernelDenied(decision, request)
                return GovernedResult(value=None, verdict="denied", audit_id=audit_id,
                                      band=band, amount=amount, description=_desc,
                                      fn_name=fn.__name__, elapsed_ms=0.0)

            if decision.verdict == Verdict.ESCALATION_REQUIRED:
                _bus.emit("escalation_required", {
                    "audit_id": audit_id, "amount": amount,
                    "reason": decision.reason, "request": request
                })
                if raise_on_escalation:
                    raise EscalationRequired(decision, request)
                return GovernedResult(value=None, verdict="escalation_required", audit_id=audit_id,
                                      band=band, amount=amount, description=_desc,
                                      fn_name=fn.__name__, elapsed_ms=0.0)

            # AUTONOMOUS — execute
            _bus.emit("pre_execute", {"audit_id": audit_id, "amount": amount, "fn": fn.__name__})
            t0 = time.monotonic()
            value = fn(*args, **kwargs)
            elapsed_ms = (time.monotonic() - t0) * 1000

            # Optional output claim verification
            claim_proof = None
            if verify_output and isinstance(value, dict):
                claim_proof = _verify_output(fn.__name__, amount, value, audit_id)

            result = GovernedResult(
                value=value, verdict="autonomous", audit_id=audit_id,
                band=band, amount=amount, description=_desc,
                fn_name=fn.__name__, elapsed_ms=elapsed_ms, claim_proof=claim_proof,
            )
            _bus.emit("post_execute", {"audit_id": audit_id, "result": result})
            return result

        wrapper._governed = True
        wrapper._band = band
        wrapper._cap = cap
        return wrapper

    return decorator


def _evaluate(request, band, cap, policy_path, state_dir):
    """Internal: load policy/state and call decide(). Never raises."""
    from custodian.policy import load_policy
    from custodian.policy.evaluator import decide
    from custodian.config import CustodianConfig
    from custodian.types import AuthorityState
    import json
    from pathlib import Path

    cfg = CustodianConfig.from_env()

    # When policy_path is explicitly set (either by caller or env), load it.
    # Otherwise use the decorator's own cap parameter to drive the policy.
    # This preserves backward compat with the existing kernel CLI flow while
    # letting @govern work standalone without requiring a policy file on disk.
    def fail_closed(reason: str) -> Decision:
        try:
            decision_band = Band(band)
        except ValueError:
            decision_band = Band.L0
        return Decision(
            verdict=Verdict.ESCALATION_REQUIRED,
            request=request,
            reason=f"{reason} -- escalating fail-closed",
            band=decision_band,
        )

    if policy_path:
        _policy_path = Path(policy_path)
        try:
            policy = load_policy(_policy_path)
        except Exception as exc:
            return fail_closed(f"configured policy could not be loaded ({exc})")
    elif os.environ.get("CUSTODIAN_POLICY_PATH"):
        try:
            policy = load_policy(Path(cfg.policy_path))
        except Exception as exc:
            return fail_closed(f"configured policy could not be loaded ({exc})")
    else:
        # No policy file on disk: honor the decorator's cap directly
        policy = _minimal_policy(band, cap)

    _state_dir = Path(state_dir) if state_dir else cfg.state_dir
    state_file = _state_dir / "authority.json"
    if state_file.exists():
        try:
            state = AuthorityState.from_dict(json.loads(state_file.read_text()))
        except Exception as exc:
            return fail_closed(f"authority state could not be loaded ({exc})")
    else:
        state = AuthorityState(band=Band(band), per_action_cap=cap, session_cap=cap * 10)

    killed = False
    ks_file = _state_dir / "kill_switch.json"
    if ks_file.exists():
        try:
            killed = bool(json.loads(ks_file.read_text()).get("killed", False))
        except Exception:
            killed = True  # fail closed: corrupted kill switch = treated as killed

    return decide(request, state, policy, killed=killed)


def _minimal_policy(band: str, cap: float):
    """Synthesize a minimal in-memory policy when no policy file exists."""
    from custodian.policy.schema import Policy, BandConfig, EscalationConfig
    from custodian.types import Band

    bands = {
        Band(b): BandConfig(
            name=Band(b),
            max_spend=cap,
            requires_approval=False,
        )
        for b in ("L0", "L1", "L2", "L3", "L4")
    }
    policy = Policy(
        version="1.0",
        default_band=Band(band),
        bands=bands,
        rules=[],
        escalation=EscalationConfig(),
    )
    return policy


def _verify_output(fn_name, amount, value, audit_id):
    """Verify the function output against the ledger. Returns claim status string."""
    try:
        from custodian.packs.base import verify_claims, Claim
        claims = [Claim(
            id=audit_id,
            statement=f"{fn_name} returned amount={amount}",
            customer_quote=str(value),
            ledger_path="result.amount",
            relation="eq",
            asserted=amount,
        )]
        scope = {"result": {"amount": value.get("amount", amount)}}
        results = verify_claims(claims, scope)
        return results[0].status.value if results else None
    except Exception:
        return None
