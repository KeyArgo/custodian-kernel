"""HTTP behavior tests for custodian.backends.twilio_verify."""
from __future__ import annotations

from pathlib import Path

import pytest
import requests

from custodian.backends.twilio_verify import TwilioVerifyBackend


class DummyResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


@pytest.fixture
def secret_file(tmp_path: Path) -> Path:
    path = tmp_path / "twilio.env"
    path.write_text(
        "TWILIO_ACCOUNT_SID=ACxxxxxxxxxx\n"
        "TWILIO_AUTH_TOKEN=shhh-secret\n"
        "TWILIO_VERIFY_SERVICE_SID=VAyyyyyyyyyy\n"
    )
    return path


class TestTwilioVerifyBackend:
    def test_constructor_stores_secret_file(self, secret_file: Path):
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        assert backend.secret_file == secret_file

    def test_constructor_stores_operator_phone(self, secret_file: Path):
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        assert backend.operator_phone == "+15551234567"

    def test_send_challenge_posts_expected_request(self, monkeypatch: pytest.MonkeyPatch, secret_file: Path):
        seen: dict = {}

        def fake_post(url, auth, data, timeout):
            seen.update({"url": url, "auth": auth, "data": data, "timeout": timeout})
            return DummyResponse({"status": "pending"})

        monkeypatch.setattr("custodian.backends.twilio_verify.requests.post", fake_post)
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        backend.send_challenge(amount=39.0, description="refund approval")
        assert seen == {
            "url": "https://verify.twilio.com/v2/Services/VAyyyyyyyyyy/Verifications",
            "auth": ("ACxxxxxxxxxx", "shhh-secret"),
            "data": {"To": "+15551234567", "Channel": "sms"},
            "timeout": 10,
        }

    def test_check_response_returns_true_for_approved_code(self, monkeypatch: pytest.MonkeyPatch, secret_file: Path):
        monkeypatch.setattr("custodian.backends.twilio_verify.requests.post", lambda *args, **kwargs: DummyResponse({"status": "approved"}))
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        assert backend.check_response("123456") is True

    def test_check_response_returns_false_for_wrong_code(self, monkeypatch: pytest.MonkeyPatch, secret_file: Path):
        monkeypatch.setattr("custodian.backends.twilio_verify.requests.post", lambda *args, **kwargs: DummyResponse({"status": "pending"}))
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        assert backend.check_response("000000") is False

    def test_check_response_posts_expected_request(self, monkeypatch: pytest.MonkeyPatch, secret_file: Path):
        seen: dict = {}

        def fake_post(url, auth, data, timeout):
            seen.update({"url": url, "auth": auth, "data": data, "timeout": timeout})
            return DummyResponse({"status": "approved"})

        monkeypatch.setattr("custodian.backends.twilio_verify.requests.post", fake_post)
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        backend.check_response("123456")
        assert seen == {
            "url": "https://verify.twilio.com/v2/Services/VAyyyyyyyyyy/VerificationCheck",
            "auth": ("ACxxxxxxxxxx", "shhh-secret"),
            "data": {"To": "+15551234567", "Code": "123456"},
            "timeout": 10,
        }

    def test_send_challenge_propagates_network_failure(self, monkeypatch: pytest.MonkeyPatch, secret_file: Path):
        monkeypatch.setattr(
            requests,
            "post",
            lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("boom")),
        )
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        with pytest.raises(requests.RequestException, match="boom"):
            backend.send_challenge(amount=39.0, description="refund approval")

    def test_check_response_propagates_network_failure(self, monkeypatch: pytest.MonkeyPatch, secret_file: Path):
        monkeypatch.setattr(
            requests,
            "post",
            lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("boom")),
        )
        backend = TwilioVerifyBackend(secret_file=secret_file, operator_phone="+15551234567")
        with pytest.raises(requests.RequestException, match="boom"):
            backend.check_response("123456")
