"""Tests for dashboard/api/operator.py's _client_ip() -- the SMS
forward-code rate limiter used to trust a client-supplied X-Forwarded-For
header unconditionally, letting a client rotate its value per request to
get a fresh rate-limit bucket every time (each real forward costs real
money via Twilio). Same bug class, and same fix, as nemotron_chat.py/
playground.py/stripe_webhook.py found and fixed earlier this session.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "dashboard"))

flask = pytest.importorskip("flask")


@pytest.fixture
def app():
    from flask import Flask
    return Flask(__name__)


def test_untrusted_header_is_ignored_by_default(app, monkeypatch):
    import dashboard.api.operator as operator_module
    monkeypatch.delenv("TRUSTED_PROXY_HEADER", raising=False)

    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "1.2.3.4"}, environ_base={"REMOTE_ADDR": "9.9.9.9"},
    ):
        assert operator_module._client_ip() == "9.9.9.9"


def test_header_is_honored_only_when_explicitly_trusted(app, monkeypatch):
    import dashboard.api.operator as operator_module
    monkeypatch.setenv("TRUSTED_PROXY_HEADER", "X-Forwarded-For")

    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "1.2.3.4"}, environ_base={"REMOTE_ADDR": "9.9.9.9"},
    ):
        assert operator_module._client_ip() == "1.2.3.4"


def test_rotating_the_header_cannot_evade_the_rate_limit_by_default(app, monkeypatch):
    """The exact bug: a client rotating X-Forwarded-For per request used to
    get a fresh _sms_allowed() bucket every time."""
    import dashboard.api.operator as operator_module
    monkeypatch.delenv("TRUSTED_PROXY_HEADER", raising=False)
    operator_module._sms_rate.clear()

    for i in range(operator_module._SMS_LIMIT):
        with app.test_request_context(
            "/", headers={"X-Forwarded-For": f"10.0.0.{i}"},
            environ_base={"REMOTE_ADDR": "9.9.9.9"},
        ):
            assert operator_module._sms_allowed(operator_module._client_ip())

    # One more, still rotating the header -- must now be blocked, since the
    # real (unforgeable) remote_addr is the same every time.
    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "10.0.0.99"}, environ_base={"REMOTE_ADDR": "9.9.9.9"},
    ):
        assert not operator_module._sms_allowed(operator_module._client_ip())
