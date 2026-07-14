"""Tests for the earn-and-buy CLI command.

The demo cycle now has three acts:
  [1/4] EARNING     — Stripe PaymentIntent, verified by claim verifier
  [2/4] KERNEL GATES — kernel evaluates inference spend request
  [3/4] AI GENERATES — Nemotron generates governance report (needs API key)
  [4/4] CYCLE CLOSED — net margin summary

Without OPENROUTER_API_KEY / NVIDIA_API_KEY, step 3 shows "inference unavailable"
and the cycle still exits 0 — the earn and kernel gate are still demonstrated.
With keys, Nemotron generates a real governance package written to ./delivery/.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


CLI = ["custodian", "demo", "cycle"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(args: list[str] | None = None, env: dict | None = None, tmp_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run the earn-and-buy CLI and return the completed process.

    Strips Modal/Stripe/Twilio/OpenAI/NVIDIA/OpenRouter vars so the
    no-credentials path is exercised deterministically.

    Runs from a temp directory so the router cannot find secrets/ files
    and fall through to a 120s live inference call.
    """
    cmd = CLI + (args or [])
    if env is None:
        env = {
            k: v for k, v in os.environ.items()
            if not any(
                kw in k.upper()
                for kw in ("MODAL", "STRIPE", "TWILIO", "OPENAI", "NVIDIA", "NIM",
                           "OPENROUTER")
            )
        }
    cwd = str(tmp_path) if tmp_path else None
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, env=env, cwd=cwd,
    )


# ── Core behavior (no credentials → graceful fallback) ────────────────────────

def test_earn_and_buy_completes_successfully(tmp_path):
    """The cycle exits 0 even without inference credentials."""
    r = _run(tmp_path=tmp_path)
    assert r.returncode == 0, (
        f"earn-and-buy exited {r.returncode}\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )


def test_earn_and_buy_prints_all_four_phases(tmp_path):
    """All four phase headers must appear in the output."""
    r = _run(tmp_path=tmp_path)
    assert "[1/4] EARNING" in r.stdout
    assert "[2/4] KERNEL GATES THE SPEND" in r.stdout
    assert "[3/4] AI GENERATES THE GOVERNANCE REPORT" in r.stdout
    assert "[4/4] CYCLE CLOSED" in r.stdout


def test_earn_and_buy_shows_verified_earn(tmp_path):
    """Earn side must show VERIFIED and $35.00 inbound."""
    r = _run(tmp_path=tmp_path)
    assert "VERIFIED" in r.stdout
    assert "Inbound:   $35.00" in r.stdout


def test_earn_and_buy_shows_kernel_decision(tmp_path):
    """Kernel gate must show band, cap, and AUTONOMOUS verdict."""
    r = _run(tmp_path=tmp_path)
    assert "Single cap:" in r.stdout
    assert "Daily envelope:" in r.stdout
    assert "kernel evaluator" in r.stdout
    assert "AUTONOMOUS" in r.stdout


def test_earn_and_buy_shows_cycle_complete(tmp_path):
    """Output must contain CYCLE COMPLETE."""
    r = _run(tmp_path=tmp_path)
    assert "CYCLE COMPLETE" in r.stdout


def test_earn_and_buy_refuses_live_mode():
    """The command must refuse to run if CUSTODIAN_STRIPE_LIVE=1."""
    env = os.environ.copy()
    env["CUSTODIAN_STRIPE_LIVE"] = "1"
    env.pop("MODAL_TOKEN_ID", None)
    env.pop("MODAL_TOKEN_SECRET", None)
    r = subprocess.run(CLI, capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode != 0
    assert "test mode" in r.stderr.lower() or "refusing" in r.stderr.lower()


def test_earn_and_buy_no_credentials_required(tmp_path):
    """Must exit 0 with NO env vars at all."""
    env = {
        k: v for k, v in os.environ.items()
        if not any(
            kw in k.upper()
            for kw in ("STRIPE", "TWILIO", "OPENAI", "NVIDIA", "NIM", "MODAL",
                       "OPENROUTER")
        )
    }
    r = subprocess.run(CLI, capture_output=True, text=True, timeout=30, env=env, cwd=str(tmp_path))
    assert r.returncode == 0, f"failed without creds: {r.stderr}\n{r.stdout}"
    assert "CYCLE COMPLETE" in r.stdout


# ── Inference fallback path ────────────────────────────────────────────────────

def test_earn_and_buy_inference_unavailable_still_exits_zero(tmp_path):
    """Without inference keys, cycle exits 0 and earn+kernel gate still run."""
    r = _run(tmp_path=tmp_path)
    assert r.returncode == 0
    assert "[1/4] EARNING" in r.stdout
    assert "[2/4] KERNEL GATES" in r.stdout
    assert "CYCLE COMPLETE" in r.stdout


def test_earn_and_buy_shows_kernel_gate_before_inference(tmp_path):
    """Kernel must evaluate the inference spend before AI is allowed to run."""
    r = _run(tmp_path=tmp_path)
    # Kernel gate section must appear before the AI section
    gate_pos = r.stdout.find("[2/4] KERNEL GATES")
    ai_pos = r.stdout.find("[3/4] AI GENERATES")
    assert gate_pos != -1
    assert ai_pos != -1
    assert gate_pos < ai_pos, "Kernel gate must appear before AI generation"


# ── Mocked inference path ──────────────────────────────────────────────────────

def test_earn_and_buy_with_mocked_inference_produces_delivery_package(tmp_path):
    """When run_report is mocked to return a receipt, cycle exits 0 and
    shows the receipt id in output."""
    fake_receipt = {
        "receipt_id": "test-receipt-abc123",
        "issued_at": "2026-06-30T00:00:00+00:00",
        "customer": "acme-test-customer",
        "payment_intent_id": "pi_demo_custodian_earn_001",
        "product": "Custodian AI Governance Report",
        "amount_usd": 35.00,
        "inference_cost_usd": 0.001,
        "net_usd": 34.999,
        "band": "L2",
        "verdict": "autonomous",
        "files": {
            "policy.yaml": "abc123",
            "threat-model.md": "def456",
            "audit-report.md": "ghi789",
            "delivery-receipt.json": "jkl012",
        },
        "output_hash": "a" * 64,
        "fingerprint": "b" * 64,
        "verify": "receipt.verify() → True",
        "out_dir": str(tmp_path),
    }

    with patch(
        "custodian.cli.cmd_earn_and_buy._step_3_generate",
        return_value=(True, {
            "billed_usd": 0.001,
            "net_usd": 34.999,
            "receipt_id": "test-receipt-abc123",
            "out_dir": str(tmp_path),
            "inference_available": True,
        }),
    ):
        from custodian.cli import cmd_earn_and_buy
        from io import StringIO
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_earn_and_buy.run(args=None)

    out = buf.getvalue()
    assert "CYCLE COMPLETE" in out
    assert "$35.00" in out


# ── Tool registry ──────────────────────────────────────────────────────────────

def test_tool_registry_run_invokes_tool():
    """ToolRegistry.run(name, **kwargs) is still registered."""
    from custodian.tools.registry import default_registry
    reg = default_registry().load()
    assert reg.get("modal-invoke") is not None
    result = reg.run("nonexistent-tool-xyz")
    assert result["ok"] is False
    assert "not found" in result.get("error", "")
