"""Tests for spark-enforcement/enforce_server.py.

No test coverage existed for this file at all before this session's
adversarial review found it completely broken: _load_policy() called
Policy.from_dict()/Policy.default(), neither of which exists on
custodian.policy.schema.Policy, so every real /decide call crashed. The
crash happened to be masked by custodian/policy/enforcer.py's client-side
fallback (a malformed error response reads as "node unreachable"), but a
remote trust anchor that fails safe by accident, not by design, needed
fixing -- along with the authorization-bypass bug underneath it (an
unauthenticated caller could otherwise forge SpendRequest's opt-in
revenue/cost/agent-id fields to defeat margin/self-dealing gates this
node's own local policy might configure).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

flask = pytest.importorskip("flask")

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def app_module(tmp_path):
    """Import enforce_server.py fresh for each test (module-level `_policy`
    cache must not leak between tests) with its own isolated policy.yaml
    location."""
    spec = importlib.util.spec_from_file_location(
        "enforce_server_under_test",
        REPO / "spark-enforcement" / "enforce_server.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Point at a policy file that doesn't exist so _load_policy() falls
    # back to the real default preset, isolated per test.
    module._POLICY_PATH = tmp_path / "no-such-policy.yaml"
    module._policy = None
    yield module


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_decide_no_longer_crashes_on_missing_policy_file(client):
    """The core bug: _load_policy() used to call Policy.from_dict()/
    Policy.default(), neither of which exists -- every call crashed with
    AttributeError. Now falls back to the real default preset."""
    r = client.post("/decide", json={
        "request": {"amount": 1.0, "description": "test"},
        "state": {"band": "L2", "per_action_cap": 250.0, "session_cap": 1000.0},
    })
    assert r.status_code == 200
    body = r.get_json()
    assert "verdict" in body
    assert body["verdict"] is not None


def test_margin_gated_policy_refuses_to_decide_remotely(app_module, tmp_path):
    """If this node's own local policy configures a gate needing inputs
    (revenue, cost, a 24h ledger) this HTTP endpoint has no way to
    independently verify, it must refuse the decision outright rather than
    evaluate a self-dealing/margin check against attacker-suppliable
    SpendRequest fields. Found in review."""
    policy_yaml = tmp_path / "policy.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_band: L2
bands:
  L2:
    max_spend: 100.00
    requires_approval: false
margins:
  minimum_margin_pct: 20.0
rules: []
escalation:
  timeout_seconds: 600
  on_timeout: deny
  retry_count: 0
""")
    app_module._POLICY_PATH = policy_yaml
    app_module._policy = None

    with app_module.app.test_client() as c:
        # The forgery the review found: claim a favorable revenue/cost to
        # defeat the margin gate, via fields nothing else corroborates.
        r = c.post("/decide", json={
            "request": {
                "amount": 1.0, "description": "test",
                "revenue": 1_000_000.0, "cost": 0.0,
            },
            "state": {"band": "L2", "per_action_cap": 250.0, "session_cap": 1000.0},
        })
        assert r.status_code == 409
        assert "local enforcement" in r.get_json()["error"]


def test_self_dealing_gated_policy_refuses_to_decide_remotely(app_module, tmp_path):
    policy_yaml = tmp_path / "policy.yaml"
    policy_yaml.write_text("""
version: "1.0"
default_band: L2
bands:
  L2:
    max_spend: 100.00
    requires_approval: false
policies:
  no_self_dealing: true
rules: []
escalation:
  timeout_seconds: 600
  on_timeout: deny
  retry_count: 0
""")
    app_module._POLICY_PATH = policy_yaml
    app_module._policy = None

    with app_module.app.test_client() as c:
        r = c.post("/decide", json={
            "request": {
                "amount": 1.0, "description": "test",
                "requester_agent_id": "agent-x", "recipient_agent_id": "agent-x-alias",
            },
            "state": {"band": "L2", "per_action_cap": 250.0, "session_cap": 1000.0},
        })
        assert r.status_code == 409


def test_ordinary_policy_without_those_gates_still_decides_normally(client):
    """The fix must not turn every request into a 409 -- only policies that
    actually configure an unverifiable gate."""
    r = client.post("/decide", json={
        "request": {"amount": 500.0, "description": "over cap"},
        "state": {"band": "L2", "per_action_cap": 2.0, "session_cap": 1000.0},
    })
    assert r.status_code == 200
    assert r.get_json()["verdict"] != "autonomous"  # over cap, but a REAL decision
