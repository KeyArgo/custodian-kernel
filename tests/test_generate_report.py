"""Tests for cmd_generate_report, cmd_send_report, and the earn-and-buy v2 cycle."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import pytest

from custodian.cli.cmd_generate_report import (
    _assign_band,
    _kernel_gate,
    _parse_response,
    _write_package,
    run_report,
)
from custodian.cli.cmd_send_report import _kernel_gate_email, run_email_step


# ── Band assignment ────────────────────────────────────────────────────────────

class TestAssignBand:
    def test_payment_tools_are_l3(self):
        for tool in ["stripe_payments", "process_refund", "billing_api", "charge_customer"]:
            band, _ = _assign_band(tool)
            assert band == "L3", f"{tool} should be L3"

    def test_delete_tools_are_l3(self):
        for tool in ["delete_transaction", "cancel_subscription", "destroy_record"]:
            band, _ = _assign_band(tool)
            assert band == "L3", f"{tool} should be L3"

    def test_write_tools_are_l2(self):
        for tool in ["send_email", "write_file", "create_record", "post_webhook"]:
            band, _ = _assign_band(tool)
            assert band == "L2", f"{tool} should be L2"

    def test_schedule_payment_is_l3(self):
        # "payment" keyword takes priority over "schedule" — correctly L3
        band, _ = _assign_band("schedule_payment")
        assert band == "L3"

    def test_read_tools_are_l0(self):
        for tool in ["web_search", "read_file", "list_directory"]:
            band, _ = _assign_band(tool)
            assert band == "L0", f"{tool} should be L0"

    def test_reason_is_non_empty(self):
        _, reason = _assign_band("stripe_payments")
        assert reason and len(reason) > 5

    def test_l3_has_self_dealing_reason(self):
        _, reason = _assign_band("stripe_payments")
        assert "self-dealing" in reason or "money" in reason or "destructive" in reason


# ── JSON parse strategies ──────────────────────────────────────────────────────

_VALID_PAYLOAD = {
    "policy_yaml": "version: '1.0'\nbands: {L2: {max_spend: 25}}\n",
    "threat_model": "## Threat Model\nSome risks.",
    "audit_report": "## Audit\nAll VERIFIED.",
    "summary": "Governance package generated.",
}


class TestParseResponse:
    def test_strategy1_direct_json(self):
        raw = json.dumps(_VALID_PAYLOAD)
        result = _parse_response(raw)
        assert result["summary"] == _VALID_PAYLOAD["summary"]

    def test_strategy1_fenced_json(self):
        raw = "```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```"
        result = _parse_response(raw)
        assert result is not None
        assert "policy_yaml" in result

    def test_strategy2_junk_prefix(self):
        raw = "Here is your response:\n" + json.dumps(_VALID_PAYLOAD)
        result = _parse_response(raw)
        assert result is not None
        assert result.get("summary") == _VALID_PAYLOAD["summary"]

    def test_strategy3_key_anchor(self):
        raw = 'Some preamble text.\n{"policy_yaml": "v: 1", "threat_model": "tm", "audit_report": "ar", "summary": "ok"}'
        result = _parse_response(raw)
        assert result is not None
        assert result["summary"] == "ok"

    def test_strategy4_fallback_stub_on_garbage(self):
        result = _parse_response("This is not JSON at all, just freetext output from the model.")
        assert result is not None
        assert "policy_yaml" in result
        assert "threat_model" in result

    def test_none_returns_none(self):
        assert _parse_response(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_response("") is None

    def test_strips_think_tags(self):
        raw = "<think>secret reasoning</think>\n" + json.dumps(_VALID_PAYLOAD)
        result = _parse_response(raw)
        assert result is not None
        assert result.get("summary") == _VALID_PAYLOAD["summary"]


# ── Kernel gate ────────────────────────────────────────────────────────────────

class TestKernelGate:
    def test_inference_spend_is_autonomous(self):
        assert _kernel_gate() is True

    def test_email_send_is_autonomous(self):
        assert _kernel_gate_email() is True


# ── Package writing ────────────────────────────────────────────────────────────

class TestWritePackage:
    def test_writes_four_files(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "delivery"
            receipt = _write_package(
                parsed=_VALID_PAYLOAD,
                inputs={"customer": "test-customer"},
                pi_id="pi_test_123",
                earn_amount=35.00,
                out_dir=out,
            )
            assert (out / "policy.yaml").exists()
            assert (out / "threat-model.md").exists()
            assert (out / "audit-report.md").exists()
            assert (out / "delivery-receipt.json").exists()

    def test_receipt_fingerprint_verifies(self):
        import hashlib
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "delivery"
            receipt = _write_package(
                parsed=_VALID_PAYLOAD,
                inputs={"customer": "test-customer"},
                pi_id="pi_test_123",
                earn_amount=35.00,
                out_dir=out,
            )
            fp = receipt["fingerprint"]
            output_hash = receipt["output_hash"]
            receipt_id = receipt["receipt_id"]
            expected = hashlib.sha256(
                f"{receipt_id}:L2:35.0:autonomous:{output_hash}".encode()
            ).hexdigest()
            assert fp == expected, "Receipt fingerprint should verify"

    def test_receipt_contains_required_fields(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "delivery"
            receipt = _write_package(
                parsed=_VALID_PAYLOAD,
                inputs={"customer": "acme"},
                pi_id="pi_abc",
                earn_amount=35.00,
                out_dir=out,
            )
            for field in ["receipt_id", "issued_at", "customer", "payment_intent_id",
                          "band", "verdict", "files", "fingerprint", "net_usd"]:
                assert field in receipt, f"Missing field: {field}"

    def test_files_dict_has_sha256_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "delivery"
            receipt = _write_package(
                parsed=_VALID_PAYLOAD,
                inputs={},
                pi_id="pi_test",
                earn_amount=35.00,
                out_dir=out,
            )
            files = receipt["files"]
            assert len(files) == 3  # policy, threat-model, audit-report
            for name, sha in files.items():
                assert len(sha) == 64, f"{name} SHA-256 should be 64 chars"


# ── run_report without inference ───────────────────────────────────────────────

class TestRunReportNoInference:
    def test_returns_none_when_no_api_key(self, capsys):
        # With no OPENROUTER_API_KEY / NVIDIA_API_KEY, should return None gracefully
        with tempfile.TemporaryDirectory() as td:
            result = run_report(
                inputs={"customer": "test", "agent_tools": "web_search"},
                pi_id="pi_test",
                earn_amount=35.00,
                out_dir=Path(td) / "out",
            )
        assert result is None
        out = capsys.readouterr().out
        assert "Kernel verdict: AUTONOMOUS" in out
        assert "unreachable" in out or "not configured" in out


# ── CLI integration: generate-report ──────────────────────────────────────────

class TestGenerateReportCLI:
    def test_exits_1_without_inference_key(self):
        result = subprocess.run(
            ["custodian", "generate-report"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "Kernel verdict: AUTONOMOUS" in result.stdout
        assert "AUTONOMOUS" in result.stdout

    def test_kernel_gate_fires_before_inference(self):
        result = subprocess.run(
            ["custodian", "generate-report"],
            capture_output=True, text=True,
        )
        stdout = result.stdout
        # Kernel gate output should appear before the unreachable message
        kernel_pos = stdout.find("Kernel verdict: AUTONOMOUS")
        unreachable_pos = stdout.find("unreachable")
        assert kernel_pos >= 0, "Kernel gate output missing"
        assert kernel_pos < unreachable_pos, "Kernel gate should fire before inference attempt"

    def test_accepts_custom_out_flag(self):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                ["custodian", "generate-report", "--out", td],
                capture_output=True, text=True,
            )
        # Should fail on inference (no key), not on arg parsing
        assert "Namespace" not in result.stderr

    def test_accepts_pi_id_and_amount_flags(self):
        result = subprocess.run(
            ["custodian", "generate-report", "--pi-id", "pi_custom", "--amount", "10.00"],
            capture_output=True, text=True,
        )
        # Should not crash on arg parsing
        assert "Namespace" not in result.stderr
        assert "not iterable" not in result.stderr


# ── send_report: graceful degradation without Resend key ──────────────────────

class TestSendReportNoKey:
    def test_run_email_step_skips_gracefully_without_key(self, capsys, monkeypatch):
        import custodian.cli.cmd_send_report as sr
        monkeypatch.setattr(sr, "_resend_key", lambda: None)
        with tempfile.TemporaryDirectory() as td:
            result = run_email_step(
                to_email="test@example.com",
                customer="acme",
                pi_id="pi_test",
                out_dir=Path(td),
                receipt={"summary": "ok", "files": {}},
            )
        assert result is False
        out = capsys.readouterr().out
        assert "AUTONOMOUS" in out


# ── earn-and-buy CLI ───────────────────────────────────────────────────────────

class TestEarnAndBuyCLI:
    def test_cycle_exits_0_without_inference_key(self):
        result = subprocess.run(
            ["custodian", "demo", "cycle"],
            capture_output=True, text=True,
        )
        # Exits 0: earn + kernel gate pass; inference failure is a warning not hard failure
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n{result.stdout}\n{result.stderr}"
        )

    def test_cycle_shows_earn_verified(self):
        result = subprocess.run(
            ["custodian", "demo", "cycle"],
            capture_output=True, text=True,
        )
        assert "VERIFIED" in result.stdout

    def test_cycle_shows_kernel_gate(self):
        result = subprocess.run(
            ["custodian", "demo", "cycle"],
            capture_output=True, text=True,
        )
        assert "AUTONOMOUS" in result.stdout

    def test_cycle_complete_message_present(self):
        result = subprocess.run(
            ["custodian", "demo", "cycle"],
            capture_output=True, text=True,
        )
        assert "CYCLE COMPLETE" in result.stdout


# ── demo receipt (isolation fix) ──────────────────────────────────────────────

class TestDemoReceiptIsolation:
    def test_demo_receipt_passes_regardless_of_workspace_policy(self, tmp_path, monkeypatch):
        """Demo should work even when run from a dir with a restrictive policy.yaml."""
        tight_policy = tmp_path / "policy.yaml"
        tight_policy.write_text(
            "version: '1.0'\ndefault_band: L3\nbands:\n"
            "  L3: {max_spend: 0, requires_approval: true}\nrules: []\n"
            "escalation: {timeout_seconds: 1, on_timeout: deny, retry_count: 0}\n"
        )
        monkeypatch.chdir(tmp_path)
        result = subprocess.run(
            ["custodian", "demo", "receipt"],
            capture_output=True, text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, (
            f"Demo receipt should pass despite restrictive workspace policy\n"
            f"{result.stdout}\n{result.stderr}"
        )
        assert "AUTONOMOUS" in result.stdout
        assert "receipt.verify() →" in result.stdout
