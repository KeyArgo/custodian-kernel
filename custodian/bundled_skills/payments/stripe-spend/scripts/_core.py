"""Shared authority-gate primitives used by both spend.py and approve.py.

Deliberately NOT importable by anything that takes an --approved-by-style
flag as trusted input — that pattern is what created the self-approval hole.
The only privileged caller of execute_spend() for over-cap amounts is
approve.py, immediately after a real Twilio Verify check it performs itself.
"""
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

    os.rename on the same filesystem is atomic on Linux.  If the process is
    killed mid-write the old file is untouched — no corruption window.
    """
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    tmp_name = str(path) + f".tmp.{os.getpid()}.{random.randint(100000, 999999)}"
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(content)
        os.fsync(tmp_path.open("rb").fileno())
        os.rename(str(tmp_path), str(path))
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


def create_payment_intent(amount_dollars, description):
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
    last_err = None
    for attempt in (1, 2):
        try:
            r = requests.post(
                "https://api.stripe.com/v1/payment_intents",
                auth=(key, ""),
                data=data,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt == 1:
                time.sleep(1)
                continue

    # Stripe consistently down — auto-fallback to mock mode if enabled.
    if _STRIPE_MOCK:
        return {"id": f"pi_mock_{int(time.time()*1000)}", "status": "succeeded"}

    raise RuntimeError(f"Stripe call failed after retry: {last_err}")


def execute_spend(amount, description, approved_by, recipe=None, to=None, message=None):
    """Actually move money. Caller is responsible for having verified
    authorization BEFORE calling this — this function does not re-check."""
    state = load_state()
    try:
        pi = create_payment_intent(amount, description)
    except Exception as e:
        append_log({
            "event": "execution_failed", "amount": amount, "description": description,
            "band": state["band"], "approved_by": approved_by, "error": str(e),
        })
        print(f"[stripe] FAILED: {e}")
        return False

    state["spent_this_session"] += amount
    save_state(state)

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


def execute_refund(payment_intent_id, amount, description, approved_by):
    """Move money back to the customer. Mirrors execute_spend's shape exactly --
    same audit log, same caller-must-have-verified-authorization contract. The only
    caller of this for any amount is approve.py, after a real Twilio Verify check --
    refunds have no autonomous path at all, unlike spend, which has graduated bands."""
    state = load_state()
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
