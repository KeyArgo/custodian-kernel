"""Tests for CustodianSession."""
import pytest
from custodian.session import CustodianSession


def test_autonomous_within_cap():
    with CustodianSession(band="L2", cap=50.00) as session:
        r = session.request(amount=5.00, description="small charge")
    assert r.ok
    assert r.verdict == "autonomous"


def test_escalation_over_cap():
    with CustodianSession(band="L2", cap=5.00) as session:
        r = session.request(amount=100.00, description="big charge")
    assert not r.ok
    assert r.verdict == "escalation_required"


def test_sub_session_lower_band_cannot_exceed_parent():
    with CustodianSession(band="L1") as parent:
        child = parent.sub_session(band="L2")  # L2 > L1 rank — should be denied
        r = child.request(amount=1.00)
    assert r.verdict == "denied"
    assert "exceeds parent ceiling" in r.reason


def test_sub_session_same_band_allowed():
    with CustodianSession(band="L2", cap=50.00) as parent:
        with parent.sub_session(band="L2", cap=50.00) as child:
            r = child.request(amount=5.00, description="same band")
    assert r.ok


def test_session_log_format():
    with CustodianSession(band="L2", cap=50.00) as session:
        session.request(amount=5.00, description="charge A")
        session.request(amount=3.00, description="charge B")
    log = session.log()
    assert "CustodianSession" in log
    assert "charge A" in log
    assert "charge B" in log


def test_session_summary():
    with CustodianSession(band="L2", cap=10.00) as session:
        session.request(amount=5.00)
        session.request(amount=100.00)  # should escalate
    summary = session.summary()
    assert summary["total"] == 2
    assert summary["autonomous"] == 1
    assert summary["escalated"] == 1
    assert summary["spent_usd"] == pytest.approx(5.00)


def test_session_spent_tracks_autonomous_only():
    with CustodianSession(band="L2", cap=50.00) as session:
        session.request(amount=10.00)  # autonomous
        session.request(amount=10.00)  # autonomous
        session.request(amount=200.00)  # escalated
    assert session._spent == pytest.approx(20.00)


def test_parent_spent_accumulates_child():
    with CustodianSession(band="L2", cap=100.00) as parent:
        with parent.sub_session(band="L2", cap=100.00) as child:
            child.request(amount=10.00)
    assert parent._spent == pytest.approx(10.00)
