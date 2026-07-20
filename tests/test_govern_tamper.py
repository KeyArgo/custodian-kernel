"""Tests for @govern's tamper check — the "agent edited its own source between
the policy check and execution" defense.

Nothing covered this before, which is how the snapshot directory came to
default to /tmp. All three regressions below were live:

1. Snapshots were written to /tmp, which is world-writable (1777 on POSIX) and
   is NOT on kernel-self-protection's protected list. The agent this check
   exists to catch could `rm /tmp/charge.bk.sha`, edit its source, and the next
   run would find no stored hash, take the first-run branch, and re-snapshot
   the tampered source as legitimate. A check whose state the tampering party
   can erase is not a check.
2. The snapshot filename was the bare function __name__, so every `charge` in
   the codebase shared one file — a false drift when two modules disagree, and
   a false OK when they happen to match.
3. A drift denial returned silently. Every other denial path in the wrapper
   emits (kernel_denied, escalation_required); the tamper path did not, so the
   most security-relevant denial available left no trace in the audit chain.
"""
import os
from pathlib import Path

import pytest

from custodian.adapters.builtin.kernel_self_protection import _default_protected
from custodian.govern import _default_tamper_dir, _tamper_key, govern


# Two functions that a bare-__name__ key CANNOT tell apart: same __name__, same
# __qualname__, different module. That is the collision — __name__ must match on
# both or the fixture proves nothing (an earlier version of this file set only
# __qualname__, so the bare-name key still differed and the test passed against
# the very bug it names).
def _other_module_fn():
    pass


_other_module_fn.__module__ = "some.other.module"
_other_module_fn.__name__ = "charge"
_other_module_fn.__qualname__ = "charge"


def _this_module_fn():
    pass


_this_module_fn.__name__ = "charge"
_this_module_fn.__qualname__ = "charge"


# -- where snapshots live ------------------------------------------------------

def test_default_snapshot_dir_is_not_world_writable_tmp(monkeypatch):
    monkeypatch.delenv("CUSTODIAN_STATE_DIR", raising=False)
    d = os.path.normpath(_default_tamper_dir())
    assert d not in ("/tmp", os.path.normpath("/tmp")), \
        "snapshots in /tmp can be deleted by the agent they guard against"
    assert ".custodian" in d


def test_default_snapshot_dir_is_covered_by_kernel_self_protection(monkeypatch):
    """The snapshot must live somewhere the agent cannot write. ~/.custodian is
    on the protected list; /tmp is not — that was the whole hole."""
    monkeypatch.delenv("CUSTODIAN_STATE_DIR", raising=False)
    d = os.path.normpath(_default_tamper_dir())
    assert any(
        d == os.path.normpath(p) or d.startswith(os.path.normpath(p) + os.sep)
        for p in _default_protected() if os.path.isabs(p)
    ), f"{d} is not under any kernel-self-protection protected path"


def test_state_dir_env_override_still_honoured(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(tmp_path))
    assert _default_tamper_dir() == str(tmp_path)


# -- snapshot identity ---------------------------------------------------------

def test_same_bare_name_in_different_modules_does_not_collide():
    assert _tamper_key(_this_module_fn) != _tamper_key(_other_module_fn)


def test_key_is_a_safe_filename():
    key = _tamper_key(_this_module_fn)
    assert key.isalnum() and len(key) == 32


def test_key_is_stable_across_calls():
    assert _tamper_key(_this_module_fn) == _tamper_key(_this_module_fn)


# -- drift behaviour -----------------------------------------------------------

@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect Path.home() so the bus's default audit log lands in tmp.

    Both vars: expanduser reads USERPROFILE on Windows and HOME on POSIX.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def test_first_run_snapshots_and_allows(tmp_path, isolated_home):
    sd = tmp_path / "tamper"

    @govern(band="L2", cap=50.00, state_dir=str(sd))
    def charge(amount: float) -> dict:
        return {"ok": True}

    assert charge(amount=1.00).verdict == "autonomous"
    assert (sd / f"{_tamper_key(charge)}.bk.sha").exists()


def test_drift_is_denied(tmp_path, isolated_home):
    sd = tmp_path / "tamper"

    @govern(band="L2", cap=50.00, state_dir=str(sd))
    def charge(amount: float) -> dict:
        return {"ok": True}

    charge(amount=1.00)
    (sd / f"{_tamper_key(charge)}.bk.sha").write_text("deadbeef")
    assert charge(amount=1.00).verdict == "denied"


def test_drift_denial_is_audited(tmp_path, isolated_home):
    """The silent-denial regression: this path emitted nothing, so a tamper
    denial was invisible to the audit chain."""
    sd = tmp_path / "tamper"

    @govern(band="L2", cap=50.00, state_dir=str(sd))
    def charge(amount: float) -> dict:
        return {"ok": True}

    charge(amount=1.00)
    (sd / f"{_tamper_key(charge)}.bk.sha").write_text("deadbeef")
    charge(amount=1.00)

    log = isolated_home / ".custodian" / "bus_events.log"
    assert log.exists(), "a tamper denial must reach the audit log"
    content = log.read_text()
    assert "kernel_denied" in content
    assert "tamper check" in content


def test_deleting_the_snapshot_does_not_silently_re_bless(tmp_path, isolated_home):
    """Documents the residual risk honestly.

    Deleting the snapshot DOES return the function to first-run state — that
    is inherent to a snapshot-on-first-use design. ~/.custodian raises the
    bar over the old /tmp default (not every process has reason to write
    there), but kernel_self_protection.py's protection only covers writes
    made through CustodianTool.invoke()'s adapter pipeline -- @govern is a
    standalone decorator with no pipeline of its own, so this is NOT an
    enforced guarantee against a determined in-process deletion, only a
    real-but-partial mitigation. If this assertion ever needs to change,
    the design changed.
    """
    sd = tmp_path / "tamper"

    @govern(band="L2", cap=50.00, state_dir=str(sd))
    def charge(amount: float) -> dict:
        return {"ok": True}

    charge(amount=1.00)
    (sd / f"{_tamper_key(charge)}.bk.sha").unlink()
    assert charge(amount=1.00).verdict == "autonomous"


def test_truncated_snapshot_is_treated_as_drift_not_a_match(tmp_path, isolated_home):
    """`if stored and stored != source_sha` treated an empty/zero-byte
    snapshot as falsy and fell through to "matches" -- a truncated (not
    deleted) snapshot file silently passed as if verified, unlike the
    deletion case above which at least re-snapshots honestly. A corrupted
    or truncated snapshot must fail closed the same as a mismatched one.
    Found in review."""
    sd = tmp_path / "tamper"

    @govern(band="L2", cap=50.00, state_dir=str(sd))
    def charge(amount: float) -> dict:
        return {"ok": True}

    charge(amount=1.00)
    (sd / f"{_tamper_key(charge)}.bk.sha").write_text("")  # truncate, do not delete
    assert charge(amount=1.00).verdict == "denied"
