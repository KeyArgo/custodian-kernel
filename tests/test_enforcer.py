"""Tests for the DGX Spark -> local-enforcement fallback in custodian.policy.enforcer.

This path had no test coverage before 2026-07-04 despite being the kernel's
documented disaster-recovery story (see docs/ARCHITECTURE.md). Verified live
against the real Spark host as part of the same audit — see session notes.
"""
import os
import tempfile

import pytest

from custodian.policy import enforcer
from custodian.types import AuthorityState, Band, Decision, SpendRequest, Verdict


@pytest.fixture(autouse=True)
def _restore_spark_state():
    """Never leave the runtime disable-flag set after a test touches it."""
    was_enabled = enforcer.spark_enabled()
    yield
    if was_enabled:
        enforcer.spark_enable()
    else:
        enforcer.spark_disable()


@pytest.fixture()
def _mode_flag(tmp_path, monkeypatch):
    """Place the mode flag file on a temp path so reads/writes are isolated."""
    flag = tmp_path / "custodian-enforcement-mode"
    monkeypatch.setattr(enforcer, "_MODE_FLAG", str(flag))
    # Start in remote-first (the default)
    flag.write_text("remote-first")
    return flag


def test_spark_unreachable_falls_back_to_local_decision(loaded_policy, default_authority, monkeypatch):
    """Point at a URL that cannot resolve -- the fallback must still return a verdict."""
    monkeypatch.setattr(enforcer, "SPARK_ENFORCE_URLS", ["http://127.0.0.1:1/decide"])
    monkeypatch.setattr(enforcer, "_remote_enabled", True)

    request = SpendRequest(amount=1.50, description="Small autonomous spend")
    result = enforcer.decide(request, default_authority, loaded_policy)

    assert result.verdict == Verdict.AUTONOMOUS


def test_spark_unreachable_still_escalates_over_cap(loaded_policy, default_authority, monkeypatch):
    monkeypatch.setattr(enforcer, "SPARK_ENFORCE_URLS", ["http://127.0.0.1:1/decide"])
    monkeypatch.setattr(enforcer, "_remote_enabled", True)

    request = SpendRequest(amount=100.0, description="Large spend while Spark is down")
    result = enforcer.decide(request, default_authority, loaded_policy)

    assert result.verdict == Verdict.ESCALATION_REQUIRED


def test_spark_a_down_falls_through_to_spark_b(loaded_policy, default_authority, monkeypatch):
    """spark-a unreachable must not skip straight to local -- spark-b should get a shot first."""
    calls = []

    def fake_try_node(url, request, state, policy, *, skill, context, killed):
        calls.append(url)
        if url == "http://192.168.50.101:8095/decide":
            return None  # spark-a down
        return Decision(
            verdict=Verdict.AUTONOMOUS, request=request, reason="spark-b served it", band=state.band,
        )

    monkeypatch.setattr(
        enforcer, "SPARK_ENFORCE_URLS",
        ["http://192.168.50.101:8095/decide", "http://192.168.50.102:8095/decide"],
    )
    monkeypatch.setattr(enforcer, "_remote_enabled", True)
    monkeypatch.setattr(enforcer, "_try_spark_node", fake_try_node)

    request = SpendRequest(amount=1.50, description="Small autonomous spend")
    result = enforcer.decide(request, default_authority, loaded_policy)

    assert calls == ["http://192.168.50.101:8095/decide", "http://192.168.50.102:8095/decide"]
    assert result.reason == "spark-b served it"


def test_runtime_disable_flag_forces_local_path(loaded_policy, default_authority):
    """The admin-panel kill switch (spark_disable/_enable) must actually route locally."""
    enforcer.spark_disable()
    assert enforcer.spark_enabled() is False

    request = SpendRequest(amount=1.50, description="Small autonomous spend")
    result = enforcer.decide(request, default_authority, loaded_policy)
    assert result.verdict == Verdict.AUTONOMOUS

    enforcer.spark_enable()
    assert enforcer.spark_enabled() is True


@pytest.mark.skipif(
    not os.environ.get("CUSTODIAN_LIVE_SPARK_TEST"),
    reason="hits the real DGX Spark host over the LAN; opt-in only",
)
def test_live_spark_health_reachable():
    """Run with CUSTODIAN_LIVE_SPARK_TEST=1 on a host that can reach a configured Spark node."""
    health = enforcer.spark_health()
    assert health.get("reachable") is True
    assert any(n.get("node") == "dgx-spark" for n in health.get("nodes", []))


# ── Enforcement mode flag ──────────────────────────────────────────────────


def test_default_mode_is_remote_first(_mode_flag):
    """When no flag file exists (or is empty), default is remote-first."""
    _mode_flag.unlink()  # remove the file — should fall back to default
    assert enforcer._read_mode() == "remote-first"
    assert enforcer.enforcement_mode_label() == "Remote-First (Spark → Local)"


def test_local_mode_skips_spark(_mode_flag, loaded_policy, default_authority, monkeypatch):
    """When mode is 'local', Spark nodes must NOT be called."""
    monkeypatch.setattr(enforcer, "_MODE_FLAG", str(_mode_flag))
    _mode_flag.write_text("local")

    calls = []

    def fake_try_node(url, request, state, policy, *, skill, context, killed):
        calls.append(url)
        return None

    monkeypatch.setattr(enforcer, "_try_spark_node", fake_try_node)

    request = SpendRequest(amount=1.50, description="Small autonomous spend")
    result = enforcer.decide(request, default_authority, loaded_policy)

    # No Spark calls at all — should have gone straight to local
    assert calls == []
    assert result.verdict == Verdict.AUTONOMOUS


def test_remote_first_mode_calls_spark(_mode_flag, loaded_policy, default_authority, monkeypatch):
    """When mode is 'remote-first', Spark nodes must be tried (fallback path)."""
    _mode_flag.write_text("remote-first")
    monkeypatch.setattr(enforcer, "_MODE_FLAG", str(_mode_flag))
    monkeypatch.setattr(enforcer, "_remote_enabled", True)
    monkeypatch.setattr(enforcer, "SPARK_ENFORCE_URLS", ["http://127.0.0.1:1/decide"])

    request = SpendRequest(amount=1.50, description="Small autonomous spend")
    result = enforcer.decide(request, default_authority, loaded_policy)

    # Spark was tried (timeout/fails), then local fallback served the verdict
    assert result.verdict == Verdict.AUTONOMOUS


def test_set_enforcement_mode_invalid_raises(_mode_flag):
    """Invalid mode values must raise ValueError."""
    with pytest.raises(ValueError, match="Invalid enforcement mode"):
        enforcer.set_enforcement_mode("bogus")


def test_toggle_via_set_enforcement_mode(_mode_flag, loaded_policy, default_authority, monkeypatch):
    """set_enforcement_mode('local') then decide() must not call Spark."""
    _mode_flag.write_text("remote-first")
    monkeypatch.setattr(enforcer, "_MODE_FLAG", str(_mode_flag))
    monkeypatch.setattr(enforcer, "_remote_enabled", True)
    monkeypatch.setattr(enforcer, "SPARK_ENFORCE_URLS", ["http://127.0.0.1:1/decide"])

    # First call: remote-first → tries Spark (unreachable) → local fallback
    request = SpendRequest(amount=1.50, description="Small autonomous spend")
    enforcer.decide(request, default_authority, loaded_policy)

    # Switch to local
    enforcer.set_enforcement_mode("local")
    assert enforcer._read_mode() == "local"

    # Second call: should NOT even try Spark
    result = enforcer.decide(request, default_authority, loaded_policy)
    assert result.verdict == Verdict.AUTONOMOUS
    assert enforcer._read_mode() == "local"


def test_label_for_local_mode(_mode_flag):
    """Human-readable label returns correct string."""
    _mode_flag.write_text("local")
    assert enforcer.enforcement_mode_label() == "Local Only (ArgoBox)"
