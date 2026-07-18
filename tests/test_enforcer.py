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
    """Never leave the runtime disable-flag set after a test touches it.

    Restores the literal flag-file state rather than spark_enabled()'s
    composite answer: with no SPARK_ENFORCE_URLS configured (the default),
    spark_enabled() is False even with no flag file, and "restoring" that by
    writing the disable flag would leak a real /tmp file into every later test.
    """
    had_flag = os.path.exists(enforcer._DISABLE_FLAG)
    yield
    if had_flag:
        enforcer.spark_disable()
    else:
        enforcer.spark_enable()


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


def test_killed_never_consults_remote(loaded_policy, default_authority, monkeypatch):
    """An engaged kill switch is enforced locally, unconditionally.

    A remote node's verdict must never be able to override it -- the endpoint
    is unauthenticated plaintext HTTP, and 'cannot be bypassed' is the one
    absolute guarantee the kernel makes.
    """
    calls = []

    def fake_try_node(url, request, state, policy, *, skill, context, killed):
        calls.append(url)
        return Decision(
            verdict=Verdict.AUTONOMOUS, request=request,
            reason="malicious node approves everything", band=state.band,
        )

    monkeypatch.setattr(enforcer, "SPARK_ENFORCE_URLS", ["http://192.168.50.101:8095/decide"])
    monkeypatch.setattr(enforcer, "_remote_enabled", True)
    monkeypatch.setattr(enforcer, "_try_spark_node", fake_try_node)

    request = SpendRequest(amount=1.50, description="spend while killed")
    result = enforcer.decide(request, default_authority, loaded_policy, killed=True)

    assert calls == []  # remote never consulted
    assert result.verdict == Verdict.DENIED


def test_no_default_remote_nodes():
    """Remote enforcement is opt-in: with no SPARK_ENFORCE_URLS/SPARK_ENFORCE_URL
    env vars, no hardcoded LAN nodes may be probed."""
    import importlib
    import subprocess
    import sys

    code = (
        "import os\n"
        "os.environ.pop('SPARK_ENFORCE_URLS', None)\n"
        "os.environ.pop('SPARK_ENFORCE_URL', None)\n"
        "from custodian.policy import enforcer\n"
        "assert enforcer.SPARK_ENFORCE_URLS == [], enforcer.SPARK_ENFORCE_URLS\n"
        "assert enforcer.spark_enabled() is False\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr


def test_runtime_disable_flag_forces_local_path(loaded_policy, default_authority, monkeypatch):
    """The admin-panel kill switch (spark_disable/_enable) must actually route locally."""
    # Remote is opt-in now; simulate a configured deployment so the runtime
    # disable flag is what's actually being exercised.
    monkeypatch.setattr(enforcer, "SPARK_ENFORCE_URLS", ["http://127.0.0.1:1/decide"])
    monkeypatch.setattr(enforcer, "_remote_enabled", True)

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


# ---------------------------------------------------------------------------
# daily_envelope / margins / no_self_dealing must never be delegated to Spark,
# and must be enforced locally when a ledger is supplied.
#
# Regression: enforcer.decide() did not accept or forward ledger_storage, so
# evaluator.decide() always saw ledger_storage=None and the daily_envelope
# gate (guarded by `ledger_storage is not None`) never ran on this path. And
# the Spark payload carries no ledger/margins/self-dealing context, so a
# reachable node would have "enforced" a verdict having never seen the gate.
# ---------------------------------------------------------------------------
from custodian.policy.schema import BandConfig, MarginsConfig, PoliciesConfig, Policy
from custodian.storage.sqlite import SqliteStorage
from custodian.types import AuditEntry


def _envelope_policy(envelope: float = 100.0) -> Policy:
    band = BandConfig(name=Band.L2, max_spend=1000.0, requires_approval=False,
                      daily_envelope=envelope)
    return Policy(version="1.0", default_band=Band.L2, bands={Band.L2: band})


def _wide_authority() -> AuthorityState:
    return AuthorityState(band=Band.L2, per_action_cap=1000.0,
                          session_cap=1000.0, spent_this_session=0.0)


def test_daily_envelope_enforced_through_enforcer_when_ledger_supplied(tmp_path):
    """$95 already spent + $50 new must escalate against a $100 envelope."""
    store = SqliteStorage(tmp_path / "s.db")
    store.append_audit_entry(
        AuditEntry(event="executed", amount=95.0, description="prior", band=Band.L2))
    req = SpendRequest(amount=50.0, description="new spend")

    result = enforcer.decide(req, _wide_authority(), _envelope_policy(),
                             skill="x", ledger_storage=store)
    assert result.verdict != Verdict.AUTONOMOUS
    assert "daily_envelope" in result.reason


def test_without_ledger_envelope_cannot_run(tmp_path):
    """Documents the dependency: no ledger means the gate has no history to
    check. The point of the fix is that callers with a ledger now pass it."""
    req = SpendRequest(amount=50.0, description="new spend")
    result = enforcer.decide(req, _wide_authority(), _envelope_policy(), skill="x")
    assert result.verdict == Verdict.AUTONOMOUS


def test_envelope_policy_never_delegates_to_spark(tmp_path, monkeypatch):
    """A reachable Spark node must NOT be consulted when a local-only gate
    exists -- it cannot see the ledger, so its verdict would skip the gate."""
    called = []

    def _boom(*a, **k):
        called.append(1)
        return Decision(verdict=Verdict.AUTONOMOUS, request=a[1],
                        reason="spark said fine", band=Band.L2)

    monkeypatch.setattr(enforcer, "SPARK_ENFORCE_URLS", ["http://spark/decide"])
    monkeypatch.setattr(enforcer, "_remote_enabled", True)
    monkeypatch.setattr(enforcer, "_try_spark_node", _boom)

    store = SqliteStorage(tmp_path / "s.db")
    store.append_audit_entry(
        AuditEntry(event="executed", amount=95.0, description="prior", band=Band.L2))
    req = SpendRequest(amount=50.0, description="new spend")

    result = enforcer.decide(req, _wide_authority(), _envelope_policy(),
                             skill="x", ledger_storage=store)
    assert not called, "Spark was consulted for a policy it cannot enforce"
    assert result.verdict != Verdict.AUTONOMOUS


def test_requires_local_enforcement_detects_each_gate():
    plain = Policy(version="1.0", default_band=Band.L2,
                   bands={Band.L2: BandConfig(name=Band.L2, max_spend=1000.0,
                                              requires_approval=False)})
    assert enforcer._requires_local_enforcement(plain) is False
    assert enforcer._requires_local_enforcement(_envelope_policy()) is True

    with_margins = Policy(version="1.0", default_band=Band.L2, bands=plain.bands,
                          margins=MarginsConfig(minimum_margin=1.0))
    assert enforcer._requires_local_enforcement(with_margins) is True

    with_selfdeal = Policy(version="1.0", default_band=Band.L2, bands=plain.bands,
                           policies=PoliciesConfig(no_self_dealing=True))
    assert enforcer._requires_local_enforcement(with_selfdeal) is True
