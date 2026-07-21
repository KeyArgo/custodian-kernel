"""Tests for per-harness/model ledger visibility grants.

Every governed decision is stamped with the harness that produced it
(codex, opencode, ...), server-side, never from a model-supplied argument.
By default a harness can only see its own receipts/approvals -- seeing
another harness's requires an explicit grant. This is the mechanism behind
"some models/harnesses can see the ledger, others can't", configurable
rather than all-or-nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from custodian.control.ledger_access_policy import (
    ALL_HARNESSES, LedgerAccessPolicy, LedgerGrant,
)


def _policy(tmp_path: Path) -> LedgerAccessPolicy:
    return LedgerAccessPolicy(tmp_path / "ledger-access-policy.json")


def test_a_harness_can_always_see_its_own_records(tmp_path):
    policy = _policy(tmp_path)
    assert policy.can_view(harness="codex", model="*", target_harness="codex")


def test_a_harness_cannot_see_another_harness_by_default(tmp_path):
    policy = _policy(tmp_path)
    assert not policy.can_view(harness="codex", model="*", target_harness="opencode")
    assert not policy.can_view(harness="opencode", model="*", target_harness="codex")


def test_explicit_grant_allows_cross_harness_visibility(tmp_path):
    policy = _policy(tmp_path)
    policy.add(LedgerGrant(harness="codex", can_view=("opencode",)))
    assert policy.can_view(harness="codex", model="*", target_harness="opencode")
    # The grant is one-directional -- opencode still cannot see codex.
    assert not policy.can_view(harness="opencode", model="*", target_harness="codex")


def test_grant_can_be_scoped_to_all_harnesses(tmp_path):
    policy = _policy(tmp_path)
    policy.add(LedgerGrant(harness="codex", can_view=(ALL_HARNESSES,)))
    assert policy.can_view(harness="codex", model="*", target_harness="opencode")
    assert policy.can_view(harness="codex", model="*", target_harness="anything-else")


def test_grant_can_be_scoped_to_one_trusted_model(tmp_path):
    policy = _policy(tmp_path)
    policy.add(LedgerGrant(harness="codex", can_view=("opencode",), model="gpt-5.6-trusted"))
    assert policy.can_view(harness="codex", model="gpt-5.6-trusted", target_harness="opencode")
    assert not policy.can_view(harness="codex", model="some-other-model", target_harness="opencode")


def test_remove_revokes_a_grant(tmp_path):
    policy = _policy(tmp_path)
    policy.add(LedgerGrant(harness="codex", can_view=("opencode",)))
    grant = policy.list()[0]
    assert policy.remove(grant.rule_id)
    assert not policy.can_view(harness="codex", model="*", target_harness="opencode")


def test_remove_unknown_rule_id_returns_false(tmp_path):
    policy = _policy(tmp_path)
    assert not policy.remove("does-not-exist")


def test_grant_requires_a_specific_harness_not_wildcard(tmp_path):
    with pytest.raises(ValueError, match="specific harness"):
        LedgerGrant(harness=ALL_HARNESSES, can_view=("opencode",)).validate()


def test_grant_requires_at_least_one_target(tmp_path):
    with pytest.raises(ValueError, match="at least one harness"):
        LedgerGrant(harness="codex", can_view=()).validate()


def test_malformed_policy_file_fails_closed_to_self_only(tmp_path):
    path = tmp_path / "ledger-access-policy.json"
    path.write_text("{ not valid json at all")
    policy = LedgerAccessPolicy(path)
    # Must not raise, and must not silently grant broad access.
    assert policy.can_view(harness="codex", model="*", target_harness="codex")
    assert not policy.can_view(harness="codex", model="*", target_harness="opencode")


def test_visible_harnesses_always_includes_self(tmp_path):
    policy = _policy(tmp_path)
    visible = policy.visible_harnesses(harness="codex", model="*")
    assert visible == frozenset({"codex"})
