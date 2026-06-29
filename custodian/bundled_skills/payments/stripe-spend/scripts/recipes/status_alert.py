"""Recipe: real SMS status alert via Twilio.

This is the actual fulfillment of "monitoring for argobox.com" — when status
changes, the agent spends real money sending a real SMS, not a free
self-hosted substitute. No free alternative exists for this; that's the point.
"""
import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, "/sandbox/.hermes/lib/python-packages")
os.environ.setdefault("SSL_CERT_FILE", "/etc/openshell-tls/ca-bundle.pem")
os.environ.setdefault("REQUESTS_CA_BUNDLE", "/etc/openshell-tls/ca-bundle.pem")

import requests  # noqa: E402

SECRET_FILE = Path("/sandbox/.hermes/secrets/twilio.env")


def _load_secrets():
    vals = {}
    for line in SECRET_FILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    return vals


def execute(to_number, message):
    """Send a real SMS via Twilio. Returns dict with sid/status, or raises."""
    secrets = _load_secrets()
    sid = secrets["TWILIO_ACCOUNT_SID"]
    token = secrets["TWILIO_AUTH_TOKEN"]
    from_number = secrets["TWILIO_FROM_NUMBER"]

    r = requests.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, token),
        data={"To": to_number, "From": from_number, "Body": message},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return {"sid": data["sid"], "status": data["status"], "to": to_number}
