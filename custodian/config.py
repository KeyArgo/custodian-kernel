"""Configuration loading for Custodian.

Secrets are never embedded in config files — only references to environment
variables or secret-file paths are. This mirrors the existing pattern in
skills/payments/stripe-spend (secrets/stripe.env, secrets/twilio.env) rather
than inventing a new one.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from custodian.exceptions import ConfigError


@dataclass
class CustodianConfig:
    state_dir: Path
    policy_path: Path
    stripe_secret_file: Path
    twilio_secret_file: Path
    pending_ttl_seconds: int = 600

    @classmethod
    def from_env(cls) -> "CustodianConfig":
        state_dir = Path(os.environ.get("CUSTODIAN_STATE_DIR", "./state")).resolve()
        policy_path = Path(os.environ.get("CUSTODIAN_POLICY_PATH", "./policy.yaml")).resolve()
        stripe_secret_file = Path(
            os.environ.get("CUSTODIAN_STRIPE_SECRET_FILE", "./secrets/stripe.env")
        ).resolve()
        twilio_secret_file = Path(
            os.environ.get("CUSTODIAN_TWILIO_SECRET_FILE", "./secrets/twilio.env")
        ).resolve()
        ttl = int(os.environ.get("CUSTODIAN_PENDING_TTL_SECONDS", "600"))
        return cls(
            state_dir=state_dir,
            policy_path=policy_path,
            stripe_secret_file=stripe_secret_file,
            twilio_secret_file=twilio_secret_file,
            pending_ttl_seconds=ttl,
        )

    def validate(self) -> None:
        if not self.state_dir.parent.exists():
            raise ConfigError(
                f"state_dir's parent does not exist: {self.state_dir.parent}"
            )
        if self.pending_ttl_seconds <= 0:
            raise ConfigError("pending_ttl_seconds must be positive")

    @property
    def authority_file(self) -> Path:
        return self.state_dir / "authority.json"

    @property
    def audit_log_file(self) -> Path:
        return self.state_dir / "audit_log.jsonl"

    @property
    def pending_approval_file(self) -> Path:
        return self.state_dir / "pending_approval.json"
