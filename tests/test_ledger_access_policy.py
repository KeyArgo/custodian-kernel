"""Tests for per-harness/model ledger visibility grants.

Every governed decision is stamped with the harness that produced it
(codex, opencode, ...), server-side, never from a model-supplied argument.
No harness sees anything by default -- not even its own receipts/approvals
-- because the agent being governed is exactly the party a denial log
exists to constrain; letting it read its own reasons/tools/verdicts turns
the ledger into an oracle it can probe to learn the enforcement boundary
and route around it. Visibility, including a harness viewing its own past
decisions, is only ever something the operator grants explicitly. This is
the mechanism behind "some models/harnesses can see the ledger, others
can't", configurable rather than all-or-nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from custodian.control.ledger_access_policy import (
    ALL_HARNESSES, LedgerAccessPolicy, LedgerGrant,
)


def _policy(tmp_path: Path) -> LedgerAccessPolicy:
    return LedgerAccessPolicy(tmp_path / "ledger-access-policy.json")


def test_a_harness_cannot_see_its_own_records_without_a_grant(tmp_path):
    policy = _policy(tmp_path)
    assert not policy.can_view(harness="codex", model="*", target_harness="codex")


def test_a_harness_cannot_see_another_harness_by_default(tmp_path):
    policy = _policy(tmp_path)
    assert not policy.can_view(harness="codex", model="*", target_harness="opencode")
    assert not policy.can_view(harness="opencode", model="*", target_harness="codex")


def test_explicit_self_grant_allows_a_harness_to_see_its_own_history(tmp_path):
    """The operator can loosen self-visibility deliberately -- it's just not
    the starting default the way it used to be."""
    policy = _policy(tmp_path)
    policy.add(LedgerGrant(harness="codex", can_view=("codex",)))
    assert policy.can_view(harness="codex", model="*", target_harness="codex")


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


def test_malformed_policy_file_fails_closed_to_nothing_visible(tmp_path):
    path = tmp_path / "ledger-access-policy.json"
    path.write_text("{ not valid json at all")
    policy = LedgerAccessPolicy(path)
    # Must not raise, and must not silently grant broad access -- not even self.
    assert not policy.can_view(harness="codex", model="*", target_harness="codex")
    assert not policy.can_view(harness="codex", model="*", target_harness="opencode")


def test_valid_json_but_malformed_grant_entry_fails_closed_to_nothing_visible(tmp_path):
    """Regression found by adversarial re-verification: a grant entry that's
    syntactically valid JSON but doesn't match LedgerGrant's constructor
    (missing the required "harness" field here) raised an uncaught
    TypeError, not the ValueError every caller actually catches -- a single
    corrupted entry broke cross-harness visibility checking for EVERY
    harness (a reliability/DoS regression), not just failing closed for the
    one malformed grant, violating this module's own stated guarantee."""
    path = tmp_path / "ledger-access-policy.json"
    path.write_text('[{"can_view": ["opencode"]}]')  # missing required "harness" key
    policy = LedgerAccessPolicy(path)
    assert not policy.can_view(harness="codex", model="*", target_harness="codex")
    assert not policy.can_view(harness="codex", model="*", target_harness="opencode")


def test_grant_entry_with_unexpected_extra_key_fails_closed_not_crashes(tmp_path):
    path = tmp_path / "ledger-access-policy.json"
    path.write_text('[{"harness": "codex", "can_view": ["opencode"], "unexpected_field": 1}]')
    policy = LedgerAccessPolicy(path)
    assert not policy.can_view(harness="codex", model="*", target_harness="codex")
    assert not policy.can_view(harness="codex", model="*", target_harness="opencode")


def test_visible_harnesses_empty_by_default(tmp_path):
    policy = _policy(tmp_path)
    visible = policy.visible_harnesses(harness="codex", model="*")
    assert visible == frozenset()
