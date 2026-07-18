"""Tests for Feature 3 — band_after_task auto-downgrade."""
from __future__ import annotations

import time

import pytest

from custodian.policy.autorank import (
    DOWNGRADE_TTL_SECONDS,
    apply_autorank,
    clear_downgrade_table,
    record_successful_request,
)
from custodian.policy.schema import BandConfig
from custodian.types import AuthorityState, Band, SpendRequest


@pytest.fixture(autouse=True)
def _reset_table():
    """Each test starts with an empty downgrade table."""
    clear_downgrade_table()
    yield
    clear_downgrade_table()


def _band_with_downgrade(name: Band, after: Band | None) -> BandConfig:
    return BandConfig(
        name=name, max_spend=10.00, requires_approval=False,
        band_after_task=after,
    )


def _state() -> AuthorityState:
    return AuthorityState(
        band=Band.L2, per_action_cap=10.0, session_cap=100.0, spent_this_session=0.0,
    )


def _request(agent_id: str = "agent-7") -> SpendRequest:
    return SpendRequest(
        amount=5.00,
        description="test",
        requester_agent_id=agent_id,
    )


class TestAutorankBackwardsCompatibility:
    def test_no_directive_returns_original_band(self):
        band = Band.L2
        cfg = _band_with_downgrade(Band.L2, after=None)
        assert apply_autorank(_state(), band, cfg, _request()) is Band.L2
        # Recording is also a no-op.
        assert record_successful_request(_state(), band, cfg, _request()) is None


class TestAutorankEffectiveBand:
    def test_record_then_apply_uses_downgrade(self):
        band = Band.L2
        cfg = _band_with_downgrade(Band.L2, after=Band.L0)
        # Before any successful request, the agent is on L2.
        assert apply_autorank(_state(), band, cfg, _request()) is Band.L2
        # A successful L2 spend records L0 as the next band.
        assert record_successful_request(_state(), band, cfg, _request()) is Band.L0
        # The next request resolves to L0.
        assert apply_autorank(_state(), band, cfg, _request()) is Band.L0

    def test_different_agents_have_independent_downgrades(self):
        band = Band.L2
        cfg = _band_with_downgrade(Band.L2, after=Band.L0)
        record_successful_request(
            _state(), band, cfg, _request(agent_id="agent-A")
        )
        # agent-A is downgraded
        assert apply_autorank(
            _state(), band, cfg, _request(agent_id="agent-A")
        ) is Band.L0
        # agent-B is unaffected
        assert apply_autorank(
            _state(), band, cfg, _request(agent_id="agent-B")
        ) is Band.L2

    def test_ttl_is_60_seconds(self):
        assert DOWNGRADE_TTL_SECONDS == 60


class TestAutorankExpiry:
    def test_expired_entry_falls_back_to_original_band(self):
        """If a downgrade's TTL has passed, apply_autorank returns the
        original band. We verify this by stuffing an entry whose
        expires_at is in the past, then calling _purge_expired with
        the real wall clock — the entry should be gone, and the next
        apply returns the original band."""
        from custodian.policy import autorank as _autorank
        band = Band.L2
        cfg = _band_with_downgrade(Band.L2, after=Band.L0)
        # Stuff a downgrade whose expires_at is 100 seconds in the past.
        _autorank._downgrade_table["agent-7"] = (Band.L0, time.time() - 100.0)
        # First apply_autorank() will purge the expired entry.
        assert apply_autorank(_state(), band, cfg, _request()) is Band.L2
        # And the table is now empty.
        assert "agent-7" not in _autorank._downgrade_table

    def test_fresh_entry_within_ttl_is_kept(self):
        """A downgrade recorded 10 seconds ago is still good for 50 more."""
        from custodian.policy import autorank as _autorank
        band = Band.L2
        cfg = _band_with_downgrade(Band.L2, after=Band.L0)
        # expires_at is 50s in the future, well within the 60s window.
        _autorank._downgrade_table["agent-7"] = (Band.L0, time.time() + 50.0)
        assert apply_autorank(_state(), band, cfg, _request()) is Band.L0


class TestAutorankEdgeCases:
    def test_request_without_agent_id_is_a_noop(self):
        """A request that doesn't carry an agent_id can't be downgraded —
        we silently return the original band, never crash."""
        band = Band.L2
        cfg = _band_with_downgrade(Band.L2, after=Band.L0)
        bare_request = SpendRequest(amount=5.00, description="no agent")
        assert apply_autorank(_state(), band, cfg, bare_request) is Band.L2
        assert record_successful_request(_state(), band, cfg, bare_request) is None

    def test_purge_does_not_grow_unbounded(self):
        from custodian.policy import autorank as _autorank
        # Stuff the table with stale entries.
        _autorank._downgrade_table["a"] = (Band.L0, 1.0)  # expired
        _autorank._downgrade_table["b"] = (Band.L0, 1.0)  # expired
        _autorank._downgrade_table["c"] = (Band.L0, 9e18) # far future
        _autorank._purge_expired(time.time())
        assert "a" not in _autorank._downgrade_table
        assert "b" not in _autorank._downgrade_table
        assert "c" in _autorank._downgrade_table


class TestNeverEscalates:
    """A downgrade table may only ever LOWER authority.

    Regression: apply_autorank returned the stored band unconditionally, so a
    downgrade recorded from a high-band task (L4 -> stored L3) raised a later
    request that had routed to a LOWER band (L1) up to L3's higher cap -- a
    privilege escalation. It now takes the stricter of stored vs routed band.
    (The earlier hunt missed this because it needs the routed band to ALSO
    carry a band_after_task, else apply_autorank early-returns before the
    table is consulted.)
    """

    def _req(self, agent="agentX"):
        r = SpendRequest(amount=1.0, description="x")
        r.requester_agent_id = agent
        return r

    def test_stored_downgrade_never_raises_a_lower_routed_band(self):
        l4 = BandConfig(name=Band.L4, max_spend=None, requires_approval=True,
                        band_after_task=Band.L3)
        record_successful_request(None, Band.L4, l4, self._req())

        # Routed to L1, and L1 also has a band_after_task so the table IS read.
        l1 = BandConfig(name=Band.L1, max_spend=0.50, requires_approval=False,
                        band_after_task=Band.L0)
        assert apply_autorank(None, Band.L1, l1, self._req()) == Band.L1

    def test_legit_downgrade_to_lower_band_still_applies(self):
        l3 = BandConfig(name=Band.L3, max_spend=50.0, requires_approval=True,
                        band_after_task=Band.L1)
        record_successful_request(None, Band.L3, l3, self._req())

        l2 = BandConfig(name=Band.L2, max_spend=2.0, requires_approval=False,
                        band_after_task=Band.L1)
        assert apply_autorank(None, Band.L2, l2, self._req()) == Band.L1
