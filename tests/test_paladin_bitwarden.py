"""Strict broker-only BWS provider tests; no real BWS token or network."""
import json
import os
import subprocess

import pytest

from paladin.bitwarden import BitwardenSecret, BitwardenSecretProvider
from paladin.broker import Broker
from paladin.errors import EgressDeniedError, ExternalSecretProviderError, GrantDeniedError
from paladin.vault import Vault


PP = "test-passphrase-123"
SECRET_ID = "123e4567-e89b-12d3-a456-426614174000"
SECRET = "bws-value-never-for-agent"


@pytest.fixture
def vault(tmp_path):
    return Vault.create(path=tmp_path / "v.paladin", passphrase=PP)


def _provider(runner):
    return BitwardenSecretProvider(
        {"payments/api": BitwardenSecret(SECRET_ID, ("api.example.test",))},
        runner=runner,
    )


def test_provider_uses_only_fixed_get_command_and_minimal_env(monkeypatch):
    seen = {}
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "broker-token")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-pass")

    def runner(argv, **kwargs):
        seen["argv"], seen["env"] = argv, kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, json.dumps({"id": SECRET_ID, "value": SECRET}), "")

    assert _provider(runner).resolve("payments/api") == SECRET
    assert seen["argv"] == ["bws", "secret", "get", SECRET_ID, "--output", "json"]
    assert seen["env"] == {"PATH": os.defpath, "BWS_ACCESS_TOKEN": "broker-token"}


def test_provider_errors_do_not_echo_cli_output(monkeypatch):
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "broker-token")
    leaked = "this-must-not-appear"

    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, leaked, leaked)

    with pytest.raises(ExternalSecretProviderError) as exc:
        _provider(runner).resolve("payments/api")
    assert leaked not in str(exc.value)


def test_external_refs_are_egress_only_and_require_host_and_grant(vault):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"id": SECRET_ID, "value": SECRET}), "")

    broker = Broker(vault, external_provider=_provider(runner))
    broker.grant("payments/api", "sandbox:test", max_band="L2",
                 allowed_hosts=["api.example.test"])
    with pytest.raises(EgressDeniedError):
        broker.build_env({"PAYMENTS": "paladin://payments/api"}, "sandbox:test")
    with pytest.raises(EgressDeniedError):
        broker.egress_request({
            "ref": "payments/api", "url": "https://wrong.example.test/v1",
            "inject": {"header": "Authorization", "format": "Bearer {value}"},
        }, requester="sandbox:test")
    assert calls == []


def test_external_ref_resolves_only_after_policy_checks(vault, monkeypatch):
    calls = []

    def runner(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"id": SECRET_ID, "value": SECRET}), "")

    broker = Broker(vault, external_provider=_provider(runner))
    descriptor = {
        "ref": "payments/api", "url": "https://api.example.test/v1",
        "inject": {"header": "Authorization", "format": "Bearer {value}"},
    }
    with pytest.raises(GrantDeniedError):
        broker.egress_request(descriptor, requester="sandbox:test")
    assert calls == []

    broker.grant("payments/api", "sandbox:test", max_band="L2",
                 allowed_hosts=["api.example.test"])
    monkeypatch.setenv("BWS_ACCESS_TOKEN", "test-broker-token")
    seen = {}

    def fake_perform(method, url, headers, body, timeout):
        seen.update(method=method, url=url, headers=headers)
        # Simulate a hostile upstream reflecting the credential.
        return {"status": 200, "headers": {"X-Echo": headers["Authorization"]},
                "body": headers["Authorization"], "truncated": False}

    broker._perform = fake_perform
    result = broker.egress_request(descriptor, requester="sandbox:test")
    assert calls == [["bws", "secret", "get", SECRET_ID, "--output", "json"]]
    assert seen["headers"]["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in result["body"]
    assert SECRET not in str(result["headers"])
