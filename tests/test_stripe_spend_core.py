"""Tests for _core.py — the money path of the stripe-spend skill.

_core.py lives outside the installed package tree (a sandbox-only script under
skills/payments/stripe-spend/scripts/, imported at runtime by spend.py /
refund.py / approve.py inside the NemoClaw sandbox), so it is loaded here via
importlib rather than a normal package import — same approach as
test_notify_pending_escalation.py. `requests` is stubbed: nothing in this file
may reach the network.

Nothing covered this module before, and all three regressions below shipped:

1. `_atomic_write` called `os.fsync(tmp_path.open("rb").fileno())`. The
   anonymous file object is refcount-freed the moment .fileno() returns, so
   fsync got a closed fd and raised OSError: [Errno 9] on EVERY call. It is the
   last step of save_state(), which runs AFTER the charge — so a successful
   spend charged the card, then raised, recording no spend and no audit entry.
   notify.py had already fixed and documented this exact line; the fix was
   never propagated.
2. Mock mode was checked only in the failure path, so CUSTODIAN_STRIPE_MOCK=true
   called Stripe for real and fell back to a mock only if the call errored —
   i.e. "mock mode" on a live key charged the card.
3. The retry POSTed a second payment_intent with no Idempotency-Key. A timeout
   is a RequestException, and a timeout does not mean the charge didn't land —
   so a lost response meant the retry charged again.
"""
import importlib.util
import json
import sys
import time
import types
from pathlib import Path

import pytest

_CORE_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "payments" / "stripe-spend" / "scripts" / "_core.py"
)


class _StubRequestException(Exception):
    pass


@pytest.fixture
def core(tmp_path, monkeypatch):
    """Import _core.py fresh with `requests` stubbed and state redirected into
    tmp_path, so tests never touch the network or the real state dir."""
    posts = []

    req = types.ModuleType("requests")
    req.exceptions = types.SimpleNamespace(RequestException=_StubRequestException)

    def _unconfigured_post(url, **kw):
        raise AssertionError(f"unexpected real Stripe call to {url}")

    req.post = _unconfigured_post
    monkeypatch.setitem(sys.modules, "requests", req)

    spec = importlib.util.spec_from_file_location("core_under_test", _CORE_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core_under_test"] = mod
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "STATE_FILE", tmp_path / "authority.json")
    monkeypatch.setattr(mod, "LOG_FILE", tmp_path / "audit_log.jsonl")
    monkeypatch.setattr(mod, "stripe_key", lambda: "sk_test_FAKE")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    mod._test_posts = posts
    mod._requests = req
    yield mod
    del sys.modules["core_under_test"]


def _audit_events(core) -> list[str]:
    if not core.LOG_FILE.exists():
        return []
    return [json.loads(l)["event"] for l in core.LOG_FILE.read_text().splitlines() if l.strip()]


# -- _atomic_write ------------------------------------------------------------

def test_atomic_write_actually_writes(core, tmp_path):
    """The regression: this raised OSError [Errno 9] on every call."""
    target = tmp_path / "state" / "x.json"
    core._atomic_write(target, '{"a": 1}')
    assert json.loads(target.read_text()) == {"a": 1}


def test_atomic_write_replaces_an_existing_file(core, tmp_path):
    """os.rename raises FileExistsError on Windows when the target exists;
    os.replace is the portable form. Overwriting state is the normal case."""
    target = tmp_path / "x.json"
    core._atomic_write(target, '{"v": 1}')
    core._atomic_write(target, '{"v": 2}')
    assert json.loads(target.read_text()) == {"v": 2}


def test_atomic_write_leaves_no_temp_files(core, tmp_path):
    target = tmp_path / "x.json"
    core._atomic_write(target, "{}")
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


# -- execute_spend: money moved must be money recorded ------------------------

def test_successful_spend_records_state_and_audit(core):
    """The headline regression: $100 charged, $0.00 recorded, no audit entry."""
    charged = []
    core.create_payment_intent = lambda a, d: (
        charged.append(a), {"id": "pi_TEST", "status": "succeeded"}
    )[1]

    assert core.execute_spend(100.00, "server costs", approved_by="operator") is True

    assert charged == [100.00], "the charge itself must still happen"
    assert json.loads(core.STATE_FILE.read_text())["spent_this_session"] == 100.00
    assert _audit_events(core) == ["executed"]


def test_failed_charge_records_no_spend(core):
    """A charge that didn't happen must not consume budget."""
    def _boom(a, d):
        raise RuntimeError("stripe down")
    core.create_payment_intent = _boom

    assert core.execute_spend(100.00, "x", approved_by="operator") is False
    assert core.load_state()["spent_this_session"] == 0.0
    assert _audit_events(core) == ["execution_failed"]


# -- mock mode ----------------------------------------------------------------

def test_mock_mode_makes_no_network_call(core, monkeypatch):
    """CUSTODIAN_STRIPE_MOCK=true must not charge. The `requests.post` stub
    raises AssertionError on any call, so reaching the network fails loudly."""
    monkeypatch.setattr(core, "_STRIPE_MOCK", True)
    pi = core.create_payment_intent(4999.00, "big one")
    assert pi["id"].startswith("pi_mock_")
    assert pi["status"] == "succeeded"


def test_mock_off_and_stripe_down_raises_rather_than_faking_success(core, monkeypatch):
    """The old failure path returned {"status": "succeeded"} when Stripe was
    unreachable, so the caller recorded spend for a charge that never happened."""
    monkeypatch.setattr(core, "_STRIPE_MOCK", False)
    core._requests.post = lambda url, **kw: (_ for _ in ()).throw(
        _StubRequestException("network down")
    )
    with pytest.raises(RuntimeError, match="Stripe call failed"):
        core.create_payment_intent(10.00, "x")


# -- idempotency --------------------------------------------------------------

def test_retry_reuses_one_idempotency_key(core, monkeypatch):
    """A timeout doesn't mean the charge didn't land. Both attempts must carry
    the SAME key so Stripe returns the original result instead of charging
    twice."""
    monkeypatch.setattr(core, "_STRIPE_MOCK", False)
    seen = []

    def _post(url, **kw):
        seen.append(kw.get("headers", {}).get("Idempotency-Key"))
        raise _StubRequestException("timeout")

    core._requests.post = _post
    with pytest.raises(RuntimeError):
        core.create_payment_intent(10.00, "x")

    assert len(seen) == 2, "expected one retry"
    assert all(seen), "every attempt must carry an Idempotency-Key"
    assert len(set(seen)) == 1, "the retry must reuse the first key, not mint a new one"


def test_distinct_calls_use_distinct_idempotency_keys(core, monkeypatch):
    """The key scopes ONE logical charge. Two separate spends are two charges
    and must not deduplicate against each other."""
    monkeypatch.setattr(core, "_STRIPE_MOCK", False)
    seen = []

    def _post(url, **kw):
        seen.append(kw.get("headers", {}).get("Idempotency-Key"))
        raise _StubRequestException("timeout")

    core._requests.post = _post
    for _ in range(2):
        with pytest.raises(RuntimeError):
            core.create_payment_intent(10.00, "x")
    assert len(set(seen)) == 2, "separate charges must not share a key"


# -- cumulative refund guard --------------------------------------------------

def test_refund_cannot_exceed_original_charge_across_multiple_refunds(core):
    """$100 charge, three $100 refunds: only the first may pass.

    The request-time check in refund.py compared each refund to the ORIGINAL
    charge, never to what was already refunded, so N full refunds each passed
    ($300 back on a $100 charge). execute_refund now sums prior refund_executed
    records and refuses once the total would exceed the charge.
    """
    core.create_refund = lambda pi, a, d: {"id": "re_mock_1", "status": "succeeded"}
    core.append_log({"event": "executed", "amount": 100.0, "description": "order",
                     "band": "L2", "payment_intent_id": "pi_X", "stripe_status": "succeeded"})

    results = [core.execute_refund("pi_X", 100.0, "refund", approved_by="op")
               for _ in range(3)]
    assert results == [True, False, False]
    assert core.refunded_amount("pi_X") == 100.0


def test_partial_refunds_sum_to_the_original(core):
    """Legitimate partial refunds are allowed up to — but not past — the total."""
    core.create_refund = lambda pi, a, d: {"id": "re_mock", "status": "succeeded"}
    core.append_log({"event": "executed", "amount": 100.0, "description": "order",
                     "band": "L2", "payment_intent_id": "pi_Y", "stripe_status": "succeeded"})

    assert core.execute_refund("pi_Y", 60.0, "partial", approved_by="op") is True
    assert core.execute_refund("pi_Y", 40.0, "rest", approved_by="op") is True
    # The books are now settled; a further cent must be refused.
    assert core.execute_refund("pi_Y", 0.01, "extra", approved_by="op") is False
    assert core.refunded_amount("pi_Y") == 100.0


# -- concurrent-spend TOCTOU --------------------------------------------------

def test_concurrent_spends_never_lose_updates_or_exceed_cap(core):
    """8 concurrent $250 spends against a $1000 session cap.

    The old path did load_state() -> charge -> increment the STALE state ->
    save, so concurrent spends both read spent=$0, both charged, and the second
    save clobbered the first's increment: money moved > money recorded, and the
    session cap was blown. execute_spend now reserves under an OS lock before
    charging, so recorded always equals charged and the cap holds exactly.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    core.save_state({"band": "L2", "per_action_cap": 1000.0,
                     "session_cap": 1000.0, "spent_this_session": 0.0})
    charged = []
    guard = threading.Lock()

    def _charge(amount, desc):
        time.sleep(0.005)  # widen the race window
        with guard:
            charged.append(amount)
        return {"id": f"pi_{len(charged)}", "status": "succeeded"}

    core.create_payment_intent = _charge

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(
            lambda i: core.execute_spend(250.0, f"spend {i}", approved_by="op"),
            range(8)))

    recorded = core.load_state()["spent_this_session"]
    assert sum(charged) == recorded, "recorded spend must equal money actually charged"
    assert sum(charged) <= 1000.0, "session cap must never be exceeded"
    assert sum(results) == 4, "exactly four $250 spends fit under a $1000 cap"


def test_failed_charge_releases_the_reservation(core):
    """A charge that raises must return its reserved budget, not leak it."""
    core.save_state({"band": "L2", "per_action_cap": 1000.0,
                     "session_cap": 1000.0, "spent_this_session": 0.0})

    def _boom(amount, desc):
        raise RuntimeError("stripe down")
    core.create_payment_intent = _boom

    assert core.execute_spend(250.0, "doomed", approved_by="op") is False
    assert core.load_state()["spent_this_session"] == 0.0, "reservation must be released"
