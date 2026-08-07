"""Tests for the guard enablement gate (custodian.guards.gate + CLI)."""
from __future__ import annotations

import json

import pytest

from custodian.cli.main import main
from custodian.guards import gate


def _state(tmp_path):
    return str(tmp_path / "state")


def test_all_guards_dormant_by_default(tmp_path):
    report = gate.status_report(_state(tmp_path))
    assert [r["enabled"] for r in report] == [False, False, False]
    assert [r["name"] for r in report] == ["codex", "claude", "hermes"]


def test_enable_roundtrip(tmp_path):
    s = _state(tmp_path)
    assert gate.enable(s, "codex") is True
    assert gate.is_enabled(s, "codex") is True
    assert gate.is_enabled(s, "claude") is False  # others untouched
    # idempotent: enabling again reports no change
    assert gate.enable(s, "codex") is False
    assert gate.disable(s, "codex") is True
    assert gate.is_enabled(s, "codex") is False
    assert gate.disable(s, "codex") is False


def test_state_file_is_single_source_of_truth(tmp_path):
    s = _state(tmp_path)
    gate.enable(s, "hermes")
    raw = json.loads((tmp_path / "state" / "guards.json").read_text())
    assert raw["version"] == 1
    assert raw["guards"]["hermes"]["enabled"] is True
    assert "updated_at" in raw["guards"]["hermes"]


def test_unknown_guard_rejected(tmp_path):
    with pytest.raises(ValueError):
        gate.enable(_state(tmp_path), "stripe")
    with pytest.raises(ValueError):
        gate.disable(_state(tmp_path), "nope")


def test_corrupt_state_without_bak_fails_closed(tmp_path):
    """Corrupt state with no valid backup must FAIL CLOSED, not go dormant.

    Regression for the final Codex finding: corruption used to disarm
    enabled guards (fail open). With no backup the gate must deny
    everything until the operator repairs the file.
    """
    s = _state(tmp_path)
    p = tmp_path / "state" / "guards.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    assert gate.is_fail_closed(s) is True
    assert gate.is_enabled(s, "codex") is False


def test_corrupt_state_restores_last_known_good_from_bak(tmp_path):
    """Corruption after a valid enable restores the .bak (last-known-good)."""
    s = _state(tmp_path)
    gate.enable(s, "codex")
    p = tmp_path / "state" / "guards.json"
    assert (tmp_path / "state" / "guards.json.bak").is_file(), "write must keep a .bak"
    p.write_text("{not json")
    assert gate.is_fail_closed(s) is False
    assert gate.is_enabled(s, "codex") is True, "last-known-good state must survive"
    # A subsequent successful write refreshes the .bak with the new state.
    gate.enable(s, "hermes")
    assert gate.is_enabled(s, "hermes") is True


def test_gate_rejects_ancestor_symlinked_state_dir(tmp_path):
    """A symlink ABOVE the state dir must be refused on read.

    Regression for the final Codex finding: only the final component was
    checked; an ancestor symlink redirected the state dir unnoticed.
    """
    real = tmp_path / "real-dir"
    real.mkdir()
    (real / "guards.json").write_text(
        '{"version": 1, "guards": {"claude": {"enabled": true}}}'
    )
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    s = str(link / "state")  # ancestor of 'state' is a symlink
    assert gate.is_enabled(s, "claude") is False
    assert gate.is_fail_closed(s) is True


def test_gate_rejects_group_or_world_writable_state_dir(tmp_path):
    """A group/world-writable state dir must FAIL CLOSED, not defer.

    A writable dir lets another local user swap the state file and disarm
    the guards — the same attack class as the symlink case.
    """
    s = _state(tmp_path)
    gate.enable(s, "codex")
    d = tmp_path / "state"
    d.chmod(0o777)  # world-writable: another local user could swap the file
    try:
        assert gate.is_enabled(s, "codex") is False
        assert gate.is_fail_closed(s) is True, "untrusted state dir must deny"
    finally:
        d.chmod(0o700)


def test_wrong_shape_state_fails_closed(tmp_path):
    """Valid JSON but the wrong shape must FAIL CLOSED, not fall back dormant.

    An attacker (or a buggy writer) can hand-craft a parseable file that
    claims 'dormant' — that must DENY, not disarm.
    """
    s = _state(tmp_path)
    p = tmp_path / "state" / "guards.json"
    p.parent.mkdir(parents=True)
    for bad in ("[]", '{"guards": null}', '{"guards": []}', '{"version": "0"}',
                '{"version": 1, "guards": {"codex": "yes"}}'):
        p.write_text(bad)
        assert gate.is_fail_closed(s) is True, f"shape {bad!r} must fail closed"


def test_state_file_missing_is_dormant_not_fail_closed(tmp_path):
    """A MISSING state file is the never-enabled baseline: dormant, not deny."""
    s = _state(tmp_path)
    assert gate.is_enabled(s, "codex") is False
    assert gate.is_fail_closed(s) is False


def test_symlinked_state_file_not_trusted(tmp_path):
    """A symlinked guards.json must not be read for enforcement state.

    Regression for the final Codex sign-off finding: write-side refused
    symlinks but read-side followed them, so an attacker able to place a
    symlink could supply a 'dormant' file and disarm the guards."""
    s = _state(tmp_path)
    real = tmp_path / "real-state"
    real.mkdir()
    (real / "guards.json").write_text(
        '{"version": 1, "guards": {"codex": {"enabled": true}}}'
    )
    link = tmp_path / "state"
    link.mkdir(parents=True)
    (link / "guards.json").symlink_to(real / "guards.json")
    # The symlinked file claims codex is enabled; the gate must refuse it.
    assert gate.is_enabled(s, "codex") is False
    assert gate.is_fail_closed(s) is True


def test_symlinked_state_dir_not_trusted(tmp_path):
    """A symlinked state directory must not be read for enforcement state."""
    real = tmp_path / "real-dir"
    real.mkdir()
    (real / "guards.json").write_text(
        '{"version": 1, "guards": {"hermes": {"enabled": true}}}'
    )
    link = tmp_path / "state"
    link.symlink_to(real, target_is_directory=True)
    assert gate.is_enabled(str(link), "hermes") is False
    assert gate.is_fail_closed(str(link)) is True


def test_concurrent_enables_are_lossless(tmp_path):
    """Two threads calling enable() concurrently must not lose updates.

    Regression for the post-Codex sign-off finding on the read-modify-write
    race. The lock + per-write unique temp + atomic replace must serialize
    them so the final state reflects both enables."""
    s = _state(tmp_path)
    import threading
    results: list[bool] = []
    def _enable(name):
        results.append(gate.enable(s, name))
    t1 = threading.Thread(target=_enable, args=("codex",))
    t2 = threading.Thread(target=_enable, args=("claude",))
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert gate.is_enabled(s, "codex") is True
    assert gate.is_enabled(s, "claude") is True
    # At most one of the threads should report "I made the change"; the
    # other may also report True if both ran the enable before either
    # had refreshed state, but the final state is the same either way.
    assert gate.is_enabled(s, "hermes") is False


def test_writes_are_atomic_via_unique_temp(tmp_path):
    """A write failure mid-temp must not corrupt the existing state file.

    Regression for the Codex finding on the predictable temp path."""
    s = _state(tmp_path)
    gate.enable(s, "codex")
    before = (tmp_path / "state" / "guards.json").read_text()
    # Force _write_state to fail by patching os.replace to raise.
    import os as _os
    real_replace = _os.replace
    def _boom(src, dst):
        raise OSError("simulated replace failure")
    _os.replace = _boom
    try:
        with pytest.raises(OSError):
            gate.enable(s, "claude")
    finally:
        _os.replace = real_replace
    after = (tmp_path / "state" / "guards.json").read_text()
    assert before == after, "existing state must be untouched after a failed write"


def test_cli_enable_and_status(tmp_path, capsys):
    s = _state(tmp_path)
    rc = main(["guards", "--state-dir", s, "enable", "claude"])
    assert rc == 0
    assert gate.is_enabled(s, "claude")
    rc = main(["guards", "--state-dir", s, "status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Claude Code guard" in out
    assert "on" in out
    assert "1 of 3 guards active" in out


def test_cli_disable(tmp_path, capsys):
    s = _state(tmp_path)
    gate.enable(s, "codex")
    main(["guards", "--state-dir", s, "disable", "codex"])
    assert not gate.is_enabled(s, "codex")


def test_bak_symlink_not_followed_on_write(tmp_path):
    """A preexisting .bak symlink must be REPLACED, never written through.

    Regression for the Codex round-3 finding: the unlink-then-copyfile
    pattern left a TOCTOU window; os.replace swaps the link itself.
    """
    s = _state(tmp_path)
    gate.enable(s, "codex")
    canary = tmp_path / "canary.txt"
    canary.write_text("attacker-content")
    bak = tmp_path / "state" / "guards.json.bak"
    bak.unlink()  # .bak exists from the first enable; replace it with the symlink
    bak.symlink_to(canary)
    gate.enable(s, "claude")  # second write refreshes the .bak
    assert canary.read_text() == "attacker-content", "symlink must not be followed"
    assert not bak.is_symlink(), ".bak must be a regular file after the write"


def test_bak_symlink_not_trusted_on_read(tmp_path):
    """A symlinked .bak must not be trusted as last-known-good on restore."""
    s = _state(tmp_path)
    gate.enable(s, "codex")
    p = tmp_path / "state" / "guards.json"
    p.write_text("{not json")
    canary = tmp_path / "canary.json"
    canary.write_text('{"version": 1, "guards": {"hermes": {"enabled": true}}}')
    bak = tmp_path / "state" / "guards.json.bak"
    bak.unlink()  # .bak exists from the enable; replace it with the symlink
    bak.symlink_to(canary)
    # The symlinked backup claims hermes enabled; the gate must refuse it
    # and fail closed instead of trusting the link's target.
    assert gate.is_fail_closed(s) is True
    assert gate.is_enabled(s, "hermes") is False
