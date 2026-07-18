"""Shared authority-gate primitives used by both spend.py and approve.py.

Deliberately NOT importable by anything that takes an --approved-by-style
flag as trusted input — that pattern is what created the self-approval hole.
The only privileged caller of execute_spend() for over-cap amounts is
approve.py, immediately after a real Twilio Verify check it performs itself.
"""
import contextlib
import json
import os
import random
import secrets
import shutil
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/sandbox/.hermes/lib/python-packages")
sys.path.insert(0, str(SKILL_DIR / "scripts"))
os.environ.setdefault("SSL_CERT_FILE", "/etc/openshell-tls/ca-bundle.pem")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "/etc/openshell-tls/ca-bundle.pem")

import requests  # noqa: E402
import recipes  # noqa: E402

STATE_FILE = SKILL_DIR / "state" / "authority.json"
LOG_FILE = SKILL_DIR / "state" / "audit_log.jsonl"
SECRET_FILE = Path("/sandbox/.hermes/secrets/stripe.env")

# Stripe mock mode — set CUSTODIAN_STRIPE_MOCK=true to simulate all charges
# instead of calling Stripe. Useful when Stripe API is down or for local testing.
# When mock mode is enabled, all payments log SIMULATED instead of charging.
_STRIPE_MOCK = os.environ.get("CUSTODIAN_STRIPE_MOCK", "").lower() in ("true", "1", "yes")


DEFAULT_STATE = {
    "band": "L2",
    "per_action_cap": 250.00,
    "session_cap": 1000.00,
    "spent_this_session": 0.0,
}


def _atomic_write(path: Path, content: str) -> None:
    """Write content atomically: write to random-named temp file, then rename.

    os.replace on the same filesystem is atomic, and unlike os.rename it also
    replaces an existing target on Windows rather than raising FileExistsError.

    fsync's fd must come from the SAME file object the whole way through (via
    a `with` block). A previous version called
    `os.fsync(tmp_path.open("rb").fileno())`, whose anonymous file object has
    no reference held once .fileno() returns, so CPython's refcounting GC
    closes it immediately and hands fsync an already-closed fd -- reproducible
    as OSError: [Errno 9] Bad file descriptor. Because _atomic_write is the
    last step of save_state(), and save_state() runs AFTER the charge, this
    raised on every successful spend: money moved, budget never decremented,
    no audit entry written. notify.py fixed this and documented it; the fix
    was never propagated here.
    """
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    tmp_name = str(path) + f".tmp.{os.getpid()}.{random.randint(100000, 999999)}"
    tmp_path = Path(tmp_name)
    try:
        with open(tmp_path, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(STATE_FILE, json.dumps(DEFAULT_STATE, indent=2))
    return dict(DEFAULT_STATE)


def save_state(state):
    _atomic_write(STATE_FILE, json.dumps(state, indent=2))


# -- cross-process state lock -------------------------------------------------
#
# The spend path is a read-modify-write on spent_this_session across a slow
# network call, which is a classic TOCTOU: two concurrent spends both loaded
# spent=$0 before either wrote, both charged, and the second save clobbered the
# first's increment -- $1000 charged, $250 recorded, and the kernel then
# believed it still had budget it had already spent. An OS advisory lock makes
# the check-and-reserve atomic; the charge itself stays OUTSIDE the lock so
# network latency never serializes unrelated spends.
try:  # POSIX
    import fcntl

    def _lock_fd(fd):
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _unlock_fd(fd):
        fcntl.flock(fd, fcntl.LOCK_UN)
except ImportError:  # Windows
    import msvcrt

    def _lock_fd(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _unlock_fd(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextlib.contextmanager
def _state_lock():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = STATE_FILE.parent / ".state.lock"
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _lock_fd(fd)
        try:
            yield
        finally:
            _unlock_fd(fd)
    finally:
        os.close(fd)


def reserve_spend(amount, session_cap):
    """Atomically check the session cap and reserve `amount` against it.

    Returns (ok, new_total). The check and the write happen under one lock, so
    two concurrent spends can never both pass a cap that only one fits under.
    The reservation is taken BEFORE charging; a failed charge releases it."""
    with _state_lock():
        state = load_state()
        new_total = round(state.get("spent_this_session", 0.0) + amount, 2)
        if session_cap is not None and new_total > round(session_cap, 2):
            return False, state.get("spent_this_session", 0.0)
        state["spent_this_session"] = new_total
        save_state(state)
        return True, new_total


def release_spend(amount):
    """Return a previously reserved `amount` to the session budget (charge
    failed). Clamped at zero so a double-release can never mint budget."""
    with _state_lock():
        state = load_state()
        state["spent_this_session"] = round(
            max(0.0, state.get("spent_this_session", 0.0) - amount), 2)
        save_state(state)


def append_log(record):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record["ts"] = time.time()
    record["iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()
        os.fsync(f.fileno())


def stripe_key():
    for line in SECRET_FILE.read_text().splitlines():
        if line.startswith("STRIPE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("STRIPE_API_KEY not found in secrets file")


def _mock_intent() -> dict:
    return {"id": f"pi_mock_{int(time.time()*1000)}", "status": "succeeded"}


def create_payment_intent(amount_dollars, description):
    # Checked BEFORE the network call, matching create_refund and matching what
    # this module's docstring promises ("simulate all charges instead of calling
    # Stripe"). A previous version checked it only in the failure path, so mock
    # mode called Stripe for real first and fell back to a mock ONLY if the call
    # errored -- i.e. enabling mock mode on a live key charged the card for real
    # and returned a successful-looking result.
    if _STRIPE_MOCK:
        return _mock_intent()
    key = stripe_key()
    cents = int(round(amount_dollars * 100))
    data = {
        "amount": cents,
        "currency": "usd",
        "description": description,
        "automatic_payment_methods[enabled]": "true",
        "automatic_payment_methods[allow_redirects]": "never",
    }
    if key.startswith("sk_test_") or key.startswith("rk_test_"):
        # pm_card_visa is Stripe's own public, well-known test-mode fixture --
        # confirming with it is what makes test-mode spends real, captured charges
        # instead of just authorized-but-empty intents. It is REJECTED by Stripe
        # outside test mode, so this branch is structurally inert on a live key --
        # not just policy-disabled, but rejected by Stripe itself if it ever runs.
        data["payment_method"] = "pm_card_visa"
        data["confirm"] = "true"
    # One key for BOTH attempts, generated before the loop. requests' timeout is
    # a RequestException, and a timeout does not mean the charge didn't land --
    # it means we don't know. Retrying without this header is how the same intent
    # gets created twice: first POST succeeds at Stripe, its response is lost,
    # the retry charges the card again. With it, Stripe returns the ORIGINAL
    # result instead of charging, so the retry is safe.
    #
    # Scope: this makes the retry *inside one call* at-most-once. It does NOT
    # survive a crash-and-reinvoke, which mints a fresh key -- that needs the
    # plan-bound authorization in docs/DESIGN-authorization-primitive.md.
    idempotency_key = secrets.token_hex(16)
    last_err = None
    for attempt in (1, 2):
        try:
            r = requests.post(
                "https://api.stripe.com/v1/payment_intents",
                auth=(key, ""),
                data=data,
                headers={"Idempotency-Key": idempotency_key},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt == 1:
                time.sleep(1)
                continue

    # Deliberately no mock fallback here. Mock mode is decided up front, so
    # reaching this point means it is off and the operator wants a real charge.
    # The previous fallback returned {"status": "succeeded"} when Stripe was
    # unreachable -- reporting a charge that never happened, which the caller
    # then recorded as spend. A failed charge must fail.
    raise RuntimeError(f"Stripe call failed after retry: {last_err}")


def execute_spend(amount, description, approved_by, recipe=None, to=None, message=None):
    """Actually move money. Caller is responsible for having verified
    authorization BEFORE calling this — but the session cap is ALSO re-checked
    here, atomically, as the last line of defense against concurrent spends.

    Order: reserve budget under a lock, THEN charge. A failed charge releases
    the reservation. This closes the TOCTOU where two concurrent spends each
    read a stale spent_this_session, both charged, and the second write lost
    the first's increment (money moved > money recorded)."""
    state = load_state()
    session_cap = state.get("session_cap")

    # Reserve first. If the cap can't fit this spend (e.g. a concurrent spend
    # already consumed the budget between the caller's check and now), refuse
    # BEFORE any money moves -- fail-safe.
    ok, _new_total = reserve_spend(amount, session_cap)
    if not ok:
        append_log({
            "event": "execution_denied", "amount": amount, "description": description,
            "band": state["band"], "approved_by": approved_by,
            "reason": f"session cap ${session_cap:.2f} would be exceeded",
        })
        print(f"[authority] DENIED -- session cap ${session_cap:.2f} would be exceeded.")
        return False

    try:
        pi = create_payment_intent(amount, description)
    except Exception as e:
        release_spend(amount)  # charge never happened — return the reservation
        append_log({
            "event": "execution_failed", "amount": amount, "description": description,
            "band": state["band"], "approved_by": approved_by, "error": str(e),
        })
        print(f"[stripe] FAILED: {e}")
        return False

    # Charge succeeded; the reservation already recorded the spend. Do NOT
    # increment again here -- that double-counted before this function reserved.

    recipe_result, recipe_error = None, None
    if recipe:
        try:
            recipe_result = recipes.run(recipe, to_number=to, message=message)
        except Exception as e:
            recipe_error = str(e)

    append_log({
        "event": "executed", "amount": amount, "description": description,
        "band": state["band"], "approved_by": approved_by,
        "payment_intent_id": pi["id"], "stripe_status": pi["status"],
        "recipe": recipe, "recipe_result": recipe_result, "recipe_error": recipe_error,
    })
    if pi["id"].startswith("pi_mock_"):
        print(f"[stripe] SIMULATED: {pi['id']} (${amount:.2f}, mock mode)")
    else:
        print(f"[stripe] PaymentIntent created: {pi['id']} (${amount:.2f}, test mode)")
    if recipe:
        print(f"[recipe:{recipe}] FAILED: {recipe_error}" if recipe_error
              else f"[recipe:{recipe}] delivered: {recipe_result}")
    print("[audit] logged: executed")
    return True


def execute_earn(amount, description):
    """Real revenue in. Unlike execute_spend, this never touches
    spent_this_session and has no caller-must-have-verified-authorization
    contract -- earn.py calls this directly, unconditionally (after only the
    kill switch and Stripe minimum checks), because receiving money carries
    none of the risk that spending it does. There is no band, no cap, no
    approval path for earning -- that asymmetry IS the policy, not a gap in
    it. The kernel still gates SPEND; it was never meant to gate income."""
    try:
        pi = create_payment_intent(amount, description)
    except Exception as e:
        append_log({
            "event": "earn_failed", "amount": amount, "description": description, "error": str(e),
        })
        print(f"[stripe] FAILED: {e}")
        return False

    append_log({
        "event": "earned", "amount": amount, "description": description,
        "payment_intent_id": pi["id"], "stripe_status": pi["status"],
    })
    if pi["id"].startswith("pi_mock_"):
        print(f"[stripe] SIMULATED revenue in: {pi['id']} (${amount:.2f}, mock mode)")
    else:
        print(f"[stripe] PaymentIntent created: {pi['id']} (${amount:.2f}, test mode, revenue in)")
    print("[audit] logged: earned")
    return True


def create_refund(payment_intent_id, amount_dollars, reason):
    if _STRIPE_MOCK:
        return {"id": f"re_mock_{int(time.time()*1000)}", "status": "succeeded"}
    key = stripe_key()
    cents = int(round(amount_dollars * 100))
    r = requests.post(
        'https://api.stripe.com/v1/refunds',
        auth=(key, ''),
        data={'payment_intent': payment_intent_id, 'amount': cents, 'reason': 'requested_by_customer'},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _sum_events(event, payment_intent_id):
    """Total amount across audit records of one event kind for one PaymentIntent."""
    if not LOG_FILE.exists():
        return 0.0
    total = 0.0
    for line in LOG_FILE.read_text().splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get('event') == event and rec.get('payment_intent_id') == payment_intent_id:
            total += float(rec.get('amount', 0.0))
    return round(total, 2)


def charged_amount(payment_intent_id):
    """Total genuinely charged against this PaymentIntent (normally one 'executed')."""
    return _sum_events('executed', payment_intent_id)


def refunded_amount(payment_intent_id):
    """Total already refunded against this PaymentIntent across ALL prior refunds."""
    return _sum_events('refund_executed', payment_intent_id)


def execute_refund(payment_intent_id, amount, description, approved_by):
    """Move money back to the customer. Mirrors execute_spend's shape exactly --
    same audit log, same caller-must-have-verified-authorization contract. The only
    caller of this for any amount is approve.py, after a real Twilio Verify check --
    refunds have no autonomous path at all, unlike spend, which has graduated bands."""
    state = load_state()

    # Authoritative cumulative-refund guard, checked at the point money actually
    # moves. The request-time check in refund.py compared a single refund to the
    # ORIGINAL charge only, so N separate refunds of the full amount each passed
    # ($100 charge -> $300 refunded across three approvals). Summing prior
    # refund_executed records makes over-refunding structurally impossible even
    # if a caller skips the request-time check or two approvals race.
    original = charged_amount(payment_intent_id)
    already = refunded_amount(payment_intent_id)
    if round(already + amount, 2) > original:
        append_log({
            'event': 'refund_denied', 'amount': amount, 'description': description,
            'payment_intent_id': payment_intent_id, 'approved_by': approved_by,
            'reason': (f'cumulative refund ${already + amount:.2f} would exceed the '
                       f'${original:.2f} originally charged (already refunded '
                       f'${already:.2f})'),
        })
        print(f'[authority] REFUND DENIED -- ${already + amount:.2f} cumulative would '
              f'exceed the ${original:.2f} charged (${already:.2f} already refunded).')
        return False

    try:
        refund = create_refund(payment_intent_id, amount, description)
    except Exception as e:
        append_log({
            'event': 'refund_failed', 'amount': amount, 'description': description,
            'payment_intent_id': payment_intent_id, 'approved_by': approved_by, 'error': str(e),
        })
        print(f'[stripe] REFUND FAILED: {e}')
        return False

    append_log({
        'event': 'refund_executed', 'amount': amount, 'description': description,
        'band': state['band'], 'approved_by': approved_by,
        'payment_intent_id': payment_intent_id, 'refund_id': refund['id'], 'stripe_status': refund['status'],
    })
    if refund['id'].startswith('re_mock_'):
        print(f"[stripe] SIMULATED REFUND: {refund['id']} (${amount:.2f}, mock mode, against {payment_intent_id})")
    else:
        print(f"[stripe] Refund created: {refund['id']} (${amount:.2f}, test mode, against {payment_intent_id})")
    print('[audit] logged: refund_executed')
    return True
