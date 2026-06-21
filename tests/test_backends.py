"""Tests for custodian.backends — configuration validation only, no real API calls."""
from __future__ import annotations

from pathlib import Path

import pytest

from custodian.backends.twilio_verify import TwilioVerifyBackend
from custodian.exceptions import BackendConfigurationError


@pytest.fixture
def valid_secrets_file(tmp_path: Path) -> Path:
    path = tmp_path / "twilio.env"
    path.write_text(
        "TWILIO_ACCOUNT_SID=ACxxxxxxxxxx\n"
        "TWILIO_AUTH_TOKEN=shhh-secret\n"
        "TWILIO_VERIFY_SERVICE_SID=VAyyyyyyyyyy\n"
    )
    return path


class TestLoadSecrets:
    def test_all_keys_present_loads_successfully(self, valid_secrets_file: Path):
        backend = TwilioVerifyBackend(secret_file=valid_secrets_file, operator_phone="+15551234567")
        secrets = backend._load_secrets()
        assert secrets["TWILIO_ACCOUNT_SID"] == "ACxxxxxxxxxx"
        assert secrets["TWILIO_AUTH_TOKEN"] == "shhh-secret"
        assert secrets["TWILIO_VERIFY_SERVICE_SID"] == "VAyyyyyyyyyy"

    def test_missing_keys_raises_error(self, tmp_path: Path):
        path = tmp_path / "partial.env"
        path.write_text("TWILIO_ACCOUNT_SID=ACxxx\nTWILIO_AUTH_TOKEN=token\n")
        backend = TwilioVerifyBackend(secret_file=path, operator_phone="+15551234567")
        with pytest.raises(BackendConfigurationError) as exc:
            backend._load_secrets()
        assert "TWILIO_VERIFY_SERVICE_SID" in str(exc.value)

    def test_empty_file_raises_error(self, tmp_path: Path):
        path = tmp_path / "empty.env"
        path.write_text("")
        backend = TwilioVerifyBackend(secret_file=path, operator_phone="+15551234567")
        with pytest.raises(BackendConfigurationError) as exc:
            backend._load_secrets()
        assert "missing required keys" in str(exc.value)

    def test_nonexistent_file_raises_error(self, tmp_path: Path):
        path = tmp_path / "nonexistent.env"
        backend = TwilioVerifyBackend(secret_file=path, operator_phone="+15551234567")
        with pytest.raises(BackendConfigurationError) as exc:
            backend._load_secrets()
        assert "secret file not found" in str(exc.value).lower()

    def test_all_missing_keys_named_in_error(self, tmp_path: Path):
        path = tmp_path / "empty_keys.env"
        path.write_text("SOME_OTHER_KEY=value\n")
        backend = TwilioVerifyBackend(secret_file=path, operator_phone="+15551234567")
        with pytest.raises(BackendConfigurationError) as exc:
            backend._load_secrets()
        msg = str(exc.value)
        assert "TWILIO_ACCOUNT_SID" in msg
        assert "TWILIO_AUTH_TOKEN" in msg
        assert "TWILIO_VERIFY_SERVICE_SID" in msg

    def test_caches_secrets_after_first_load(self, valid_secrets_file: Path):
        backend = TwilioVerifyBackend(secret_file=valid_secrets_file, operator_phone="+15551234567")
        first = backend._load_secrets()
        second = backend._load_secrets()
        assert first is second
