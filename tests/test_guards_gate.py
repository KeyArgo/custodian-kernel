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
