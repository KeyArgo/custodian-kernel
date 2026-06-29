"""Approval-code delivery + pending-escalation tracking — real Twilio Verify.

The code itself is generated and held only by Twilio's servers and the
human's phone. It is never returned to this process or written to any file
the agent can read — that's what makes self-approval structurally
impossible, not just discouraged by convention.
"""
import json
import os
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/sandbox/.hermes/lib/python-packages")
os.environ.setdefault("SSL_CERT_FILE", "/etc/openshell-tls/ca-bundle.pem")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "/etc/openshell-tls/ca-bundle.pem")

import requests  # noqa: E402

SECRET_FILE = Path("/sandbox/.hermes/secrets/twilio.env")
PENDING_FILE = SKILL_DIR / "state" / "pending_approval.json"
OPERATOR_PHONE = os.environ.get("HERMES_OPERATOR_PHONE", "+17196487887")


def _load_secrets():
    vals = {}
    for line in SECRET_FILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def write_pending(amount, description, reason, kind="spend", payment_intent_id=None):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps({
        "amount": amount, "description": description, "reason": reason,
        "created_at": time.time(), "kind": kind, "payment_intent_id": payment_intent_id,
    }, indent=2))


def send_approval_code(amount: float, description: str) -> bool:
    secrets = _load_secrets()
    sid = secrets["TWILIO_ACCOUNT_SID"]
    token = secrets["TWILIO_AUTH_TOKEN"]
    verify_service = secrets["TWILIO_VERIFY_SERVICE_SID"]

    r = requests.post(
        f"https://verify.twilio.com/v2/Services/{verify_service}/Verifications",
        auth=(sid, token),
        data={"To": OPERATOR_PHONE, "Channel": "sms"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    print(f"[notify:TWILIO VERIFY] Real approval code sent to operator phone "
          f"for ${amount:.2f} spend ('{description}'). Verification status: {data.get('status')}.")
    return True


def check_approval_code(code: str) -> bool:
    secrets = _load_secrets()
    sid = secrets["TWILIO_ACCOUNT_SID"]
    token = secrets["TWILIO_AUTH_TOKEN"]
    verify_service = secrets["TWILIO_VERIFY_SERVICE_SID"]

    r = requests.post(
        f"https://verify.twilio.com/v2/Services/{verify_service}/VerificationCheck",
        auth=(sid, token),
        data={"To": OPERATOR_PHONE, "Code": code},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("status") == "approved"
