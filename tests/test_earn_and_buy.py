"""Tests for the earn-and-buy CLI command.

This is the third act of the demo video: the agent earns, the kernel
gates the spend, and the verifier proves both sides. The hardcoded
data flows through the production verify_claims() function, so the
verdicts are real — only the input shape is fixed.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest


CLI = ["custodian", "earn-and-buy"]


def _run(args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run the earn-and-buy CLI and return the completed process."""
    cmd = CLI + (args or [])
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
    )


def test_earn_and_buy_completes_successfully():
    """The full cycle should print exit 0 and 'CYCLE COMPLETE'."""
    r = _run()
    assert r.returncode == 0, (
        f"earn-and-buy exited {r.returncode}\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "CYCLE COMPLETE" in r.stdout
    assert "Custodian earn-and-buy" in r.stdout or "EARN-AND-BUY" in r.stdout


def test_earn_and_buy_prints_all_four_phases():
    """All four phases should be present in the output."""
    r = _run()
    assert "[1/4] EARNING" in r.stdout
    assert "[2/4] KERNEL GATES THE SPEND" in r.stdout
    assert "[3/4] THE SPEND HAPPENS" in r.stdout
    assert "[4/4] CYCLE CLOSED" in r.stdout


def test_earn_and_buy_shows_verified_on_both_sides():
    """Both the earn and the spend should print VERIFIED."""
    r = _run()
    # Earn phase
    assert "VERIFIED" in r.stdout
    # Net = $0.00 means inbound == outbound
    assert "Net:       $0.00" in r.stdout
    assert "Inbound:   $0.50" in r.stdout
    assert "Outbound:  $0.50" in r.stdout


def test_earn_and_buy_shows_kernel_decision():
    """The kernel gating logic should be visible (cap, envelope, self-approval)."""
    r = _run()
    assert "Single cap:" in r.stdout
    assert "Daily envelope:" in r.stdout
    assert "self-approval check" in r.stdout
    assert "AUTONOMOUS" in r.stdout


def test_earn_and_buy_refuses_live_mode():
    """The command should refuse to run if CUSTODIAN_STRIPE_LIVE=1."""
    env = os.environ.copy()
    env["CUSTODIAN_STRIPE_LIVE"] = "1"
    r = subprocess.run(
        CLI, capture_output=True, text=True, timeout=30, env=env,
    )
    assert r.returncode != 0
    assert "test mode" in r.stderr.lower() or "refusing" in r.stderr.lower()


def test_earn_and_buy_no_credentials_required():
    """The command must work with NO env vars, NO Stripe key, NO Twilio key."""
    # Strip any potential env vars
    env = {
        k: v for k, v in os.environ.items()
        if not any(
            kw in k.upper()
            for kw in ("STRIPE", "TWILIO", "OPENAI", "NVIDIA", "NIM")
        )
    }
    r = subprocess.run(
        CLI, capture_output=True, text=True, timeout=30, env=env,
    )
    assert r.returncode == 0, f"failed without creds: {r.stderr}"
    assert "CYCLE COMPLETE" in r.stdout
