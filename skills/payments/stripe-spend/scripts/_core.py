"""Shared authority-gate primitives used by both spend.py and approve.py.

Deliberately NOT importable by anything that takes an --approved-by-style
flag as trusted input — that pattern is what created the self-approval hole.
The only privileged caller of execute_spend() for over-cap amounts is
approve.py, immediately after a real Twilio Verify check it performs itself.
"""
import json
import os
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

DEFAULT_STATE = {
    "band": "L2",
    "per_action_cap": 2.00,
    "session_cap": 10.00,
    "spent_this_session": 0.0,
}


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(DEFAULT_STATE, indent=2))
    return dict(DEFAULT_STATE)


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def append_log(record):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record["ts"] = time.time()
    record["iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def stripe_key():
    for line in SECRET_FILE.read_text().splitlines():
        if line.startswith("STRIPE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("STRIPE_API_KEY not found in secrets file")


def create_payment_intent(amount_dollars, description):
    key = stripe_key()
    cents = int(round(amount_dollars * 100))
    last_err = None
    for attempt in (1, 2):
        try:
            r = requests.post(
                "https://api.stripe.com/v1/payment_intents",
                auth=(key, ""),
                data={
                    "amount": cents,
                    "currency": "usd",
                    "description": description,
                    "automatic_payment_methods[enabled]": "true",
                },
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt == 1:
                time.sleep(1)
                continue
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
    print(f"[stripe] PaymentIntent created: {pi['id']} (${amount:.2f}, test mode)")
    if recipe:
        print(f"[recipe:{recipe}] FAILED: {recipe_error}" if recipe_error
              else f"[recipe:{recipe}] delivered: {recipe_result}")
    print("[audit] logged: executed")
    return True
