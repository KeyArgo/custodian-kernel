"""Talaria dashboard tests — API auth, vault metadata-only guarantee,
and the policy read/write round-trip, via Flask's test client (no
network bind needed)."""
import json

import pytest

from paladin.vault import Vault
from talaria.dashboard import create_app
from talaria.denial_log import DenialLog


@pytest.fixture
def vault(tmp_path):
    return Vault.create(path=tmp_path / "v.paladin", passphrase="pp")


@pytest.fixture
def denial_log(tmp_path):
    return DenialLog(dir_path=tmp_path / "denials")


@pytest.fixture
def client(vault, denial_log, tmp_path):
    app = create_app(vault=vault, denial_log=denial_log,
                     policy_path=tmp_path / "policy.yaml", token="test-token")
    app.config["TESTING"] = True
    return app.test_client()


def _get(client, path, **kw):
    return client.get(path + ("&" if "?" in path else "?") + "token=test-token", **kw)


def _post(client, path, body):
    return client.post(path + "?token=test-token", json=body)


# -- auth ----------------------------------------------------------------

def test_api_requires_token(client):
    r = client.get("/api/status")
    assert r.status_code == 401


def test_api_wrong_token_rejected(client):
    r = client.get("/api/status?token=wrong")
    assert r.status_code == 401


def test_index_does_not_require_token(client):
    # The page itself must load so its embedded JS can start making the
    # (correctly authenticated) fetch() calls -- only /api/ is gated.
    r = client.get("/")
    assert r.status_code == 200
    assert b"test-token" in r.data


# -- status ----------------------------------------------------------------

def test_status_reports_vault_and_policy_state(client, vault):
    r = _get(client, "/api/status")
    body = r.get_json()
    assert body["vault_open"] is True
    assert body["vault_path"] == str(vault.path)


# -- vault: metadata-only guarantee -----------------------------------------

def test_vault_list_never_includes_value(client, vault):
    vault.add("stripe_sk", "sk_live_should_never_appear_in_response", env_var="STRIPE_KEY")
    r = _get(client, "/api/vault")
    body = r.get_json()
    blob = json.dumps(body)
    assert "sk_live_should_never_appear_in_response" not in blob
    assert body["entries"][0]["name"] == "stripe_sk"
    assert body["entries"][0]["length"] == len("sk_live_should_never_appear_in_response")


def test_vault_add_via_post(client, vault):
    r = _post(client, "/api/vault", {"name": "new_secret", "value": "abc123", "env_var": "NEW_SECRET"})
    assert r.status_code == 201
    assert r.get_json()["ref"] == "paladin://new_secret"
    assert vault._require("new_secret").value == "abc123"


def test_vault_add_requires_name_and_value(client):
    r = _post(client, "/api/vault", {"name": "", "value": "x"})
    assert r.status_code == 400
    r2 = _post(client, "/api/vault", {"name": "x", "value": ""})
    assert r2.status_code == 400


def test_vault_endpoint_without_open_vault(vault, denial_log, tmp_path):
    app = create_app(vault=None, denial_log=denial_log,
                     policy_path=tmp_path / "policy.yaml", token="t")
    c = app.test_client()
    r = c.get("/api/vault?token=t")
    assert r.status_code == 503


# -- policy: read/write round-trip, kernel-grade guards not exposed --------

def test_policy_round_trip(client, tmp_path):
    body = _get(client, "/api/policy").get_json()
    assert "self_protection" not in body["guards"]  # kernel-grade, not togglable
    assert body["kernel_grade_guards"] == ["self_protection", "prompt_injection", "secret_leak"]

    body["tools_forbid"] = ["stripe-payout"]
    body["guards"]["pii"] = False
    r = _post(client, "/api/policy", body)
    assert r.get_json()["ok"] is True

    reloaded = _get(client, "/api/policy").get_json()
    assert reloaded["tools_forbid"] == ["stripe-payout"]
    assert reloaded["guards"]["pii"] is False


def test_policy_save_does_not_touch_kernel_grade_guards(client):
    body = _get(client, "/api/policy").get_json()
    _post(client, "/api/policy", body)
    from talaria.policy import load_policy, build_pipeline
    saved = load_policy(client.application.config["POLICY_PATH"])
    pipe = build_pipeline(saved)
    names = [a.name for a in pipe.adapters]
    assert "kernel-self-protection" in names  # still unconditional after a dashboard save
