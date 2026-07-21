"""Tests for custodian.policy.gate.kernel_gate -- the shared decision logic
extracted from CustodianTool._kernel_decide so every governed call path
(skill scripts, the delegated executor, the inference router) uses one
implementation instead of parallel copies that could silently drift."""
from pathlib import Path

from custodian.policy.gate import kernel_gate


def test_small_amount_is_autonomous(tmp_path):
    result = kernel_gate(1.00, action="test:small", state_dir=tmp_path)
    assert result["verdict"] == "autonomous"


def test_huge_amount_escalates(tmp_path):
    result = kernel_gate(999_999.99, action="test:huge", state_dir=tmp_path)
    assert result["verdict"] != "autonomous"


def test_kill_switch_denies_everything(tmp_path):
    (tmp_path / "kill_switch.json").write_text('{"killed": true}')
    result = kernel_gate(0.01, action="test:tiny", state_dir=tmp_path)
    assert result["verdict"] == "denied"


def test_corrupted_kill_switch_file_fails_closed_to_denied(tmp_path):
    (tmp_path / "kill_switch.json").write_text("not-json")
    result = kernel_gate(0.01, action="test:tiny", state_dir=tmp_path)
    assert result["verdict"] == "denied"


def test_corrupted_policy_escalates_fail_closed_with_fallback_band(tmp_path):
    (tmp_path / "policy.yaml").write_text("not: a valid policy\nbands: 5\n")
    result = kernel_gate(1.00, action="test:x", state_dir=tmp_path, fallback_band="L3")
    assert result["verdict"] == "escalation_required"
    assert result["band"] == "L3"
