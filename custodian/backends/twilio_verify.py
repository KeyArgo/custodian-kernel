"""Twilio Verify approval backend.

Ports the real Twilio Verify integration from skills/payments/stripe-spend/
scripts/notify.py (same API calls, same secret-file-loading pattern) into
the abstract ApprovalBackend interface so the policy engine can dispatch
through it without knowing which backend is wired. HTTP errors propagate
as exceptions; no retry logic is implemented.

The code itself is generated and held only by Twilio's servers and the
human's phone. It is never returned to this process or written to any file
the agent can read -- that's what makes self-approval structurally impossible.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import requests

from custodian.backends.base import ApprovalBackend
from custodian.exceptions import BackendConfigurationError

logger = logging.getLogger(__name__)


class TwilioVerifyBackend(ApprovalBackend):
    name = "twilio_verify"

    def __init__(self, secret_file: Path, operator_phone: str):
        self.secret_file = secret_file
        self.operator_phone = operator_phone
        self._secrets: Optional[dict[str, str]] = None

    def _load_secrets(self) -> dict[str, str]:
        if self._secrets is not None:
            return self._secrets
        if not self.secret_file.exists():
            raise BackendConfigurationError(
                f"Twilio secret file not found: {self.secret_file}"
            )
        vals: dict[str, str] = {}
        for line in self.secret_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip()
        missing = []
        for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_VERIFY_SERVICE_SID"):
            if key not in vals:
                missing.append(key)
        if missing:
            raise BackendConfigurationError(
                f"Twilio secret file {self.secret_file} is missing required keys: {missing}"
            )
        self._secrets = vals
        return vals

    def send_challenge(self, *, amount: float, description: str) -> None:
        secrets = self._load_secrets()
        sid = secrets["TWILIO_ACCOUNT_SID"]
        token = secrets["TWILIO_AUTH_TOKEN"]
        verify_service = secrets["TWILIO_VERIFY_SERVICE_SID"]

        r = requests.post(
            f"https://verify.twilio.com/v2/Services/{verify_service}/Verifications",
            auth=(sid, token),
            data={"To": self.operator_phone, "Channel": "sms"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        logger.info(
            "Twilio Verify code sent to operator for $%.2f spend ('%s'). Status: %s",
            amount, description, data.get("status"),
        )

    def check_response(self, code: str) -> bool:
        secrets = self._load_secrets()
        sid = secrets["TWILIO_ACCOUNT_SID"]
        token = secrets["TWILIO_AUTH_TOKEN"]
        verify_service = secrets["TWILIO_VERIFY_SERVICE_SID"]

        r = requests.post(
            f"https://verify.twilio.com/v2/Services/{verify_service}/VerificationCheck",
            auth=(sid, token),
            data={"To": self.operator_phone, "Code": code},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("status") == "approved"
