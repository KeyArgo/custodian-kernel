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


def test_corrupt_state_falls_back_dormant(tmp_path):
    s = _state(tmp_path)
    p = tmp_path / "state" / "guards.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json")
    assert gate.is_enabled(s, "codex") is False


def test_wrong_shape_state_falls_back_dormant(tmp_path):
    """Valid JSON but the wrong shape (e.g. someone hand-edits or a buggy
    prior version wrote a list) must not crash is_enabled — it must fall
    back to the dormant baseline. Regression for the post-Codex sign-off
    finding on the gate's corrupt-file fall-back."""
    s = _state(tmp_path)
    p = tmp_path / "state" / "guards.json"
    p.parent.mkdir(parents=True)
    for bad in ("[]", '{"guards": null}', '{"guards": []}', '{"version": "0"}',
                '{"version": 1, "guards": {"codex": "yes"}}'):
        p.write_text(bad)
        assert gate.is_enabled(s, "codex") is False, f"shape {bad!r} should be dormant"


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
