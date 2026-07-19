"""Shared fixtures for the custodian test suite."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from custodian.policy.loader import load_policy
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuthorityState, Band


@pytest.fixture(autouse=True)
def isolate_host_configuration(monkeypatch, tmp_path):
    """The test suite must not consume security state from the host.

    A developer machine with PALADIN_KEYFILE set caused every passphrase-based
    CLI test to use that unrelated keyfile and report a tampered vault. Tests
    that exercise env unlocking set their own values after this fixture runs.

    Tamper snapshots are deliberately persistent in production.  Sharing the
    developer's real snapshot directory in tests, however, makes an intentional
    source edit look like a runtime attack on the next test run.  Give each test
    a protected-by-isolation state root so it still exercises snapshot creation
    and comparison without consuming or modifying operator state.
    """
    for name in (
        "PALADIN_KEYFILE", "PALADIN_PASSPHRASE",
        "WARDEN_KEYFILE", "WARDEN_PASSPHRASE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(tmp_path / "custodian-state"))

DEFAULT_POLICY_YAML = """\
version: "1.0"
default_band: L2

bands:
  L0:
    max_spend: 0
    requires_approval: false
    description: "Read-only, no real-world effects"
  L1:
    max_spend: 0.50
    requires_approval: false
    description: "Trivial autonomous spend"
  L2:
    max_spend: 2.00
    requires_approval: false
    approval_backend: twilio_verify
    description: "Standard autonomous band -- escalates above its cap or the session budget"
  L3:
    max_spend: 50.00
    requires_approval: true
    approval_backend: twilio_verify
    description: "Always requires human approval, regardless of amount"
  L4:
    max_spend: null
    requires_approval: true
    approval_backend: twilio_verify
    description: "Unlimited, but always requires approval -- for critical/irreversible actions"

rules: []

escalation:
  timeout_seconds: 600
  on_timeout: deny
  retry_count: 0
"""


@pytest.fixture
def tmp_policy_file(tmp_path: Path) -> Path:
    path = tmp_path / "policy.yaml"
    path.write_text(DEFAULT_POLICY_YAML)
    return path


@pytest.fixture
def loaded_policy(tmp_policy_file: Path):
    return load_policy(tmp_policy_file)


@pytest.fixture
def default_authority() -> AuthorityState:
    return AuthorityState(
        band=Band.L2,
        per_action_cap=2.00,
        session_cap=10.00,
        spent_this_session=0.0,
    )


@pytest.fixture
def partial_authority() -> AuthorityState:
    return AuthorityState(
        band=Band.L2,
        per_action_cap=2.00,
        session_cap=10.00,
        spent_this_session=4.50,
    )


@pytest.fixture
def tmp_db(tmp_path: Path) -> SqliteStorage:
    return SqliteStorage(tmp_path / "test.db")
