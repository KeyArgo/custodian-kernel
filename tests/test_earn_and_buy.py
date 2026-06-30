"""Tests for the earn-and-buy CLI command.

This is the third act of the demo video: the agent earns, the kernel
gates the spend, and the verifier proves both sides. The hardcoded
data flows through the production verify_claims() function, so the
verdicts are real — only the input shape is fixed.

With MODAL_TOKEN_ID + MODAL_TOKEN_SECRET set, step [3/4] calls the real
modal-invoke tool and the verifier proves the actual billed amount.
Without those env vars, the command falls back to a clearly-labelled
simulated response and the verifier still runs end-to-end.
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

import pytest


CLI = ["custodian", "demo", "cycle"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(args: list[str] | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the earn-and-buy CLI and return the completed process.

    If `env` is None, we strip Modal/Stripe/Twilio/OpenAI/NVIDIA vars so
    the no-credentials path is exercised deterministically.
    """
    cmd = CLI + (args or [])
    if env is None:
        env = {
            k: v for k, v in os.environ.items()
            if not any(
                kw in k.upper()
                for kw in ("MODAL", "STRIPE", "TWILIO", "OPENAI", "NVIDIA", "NIM")
            )
        }
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, env=env,
    )


# ── Original behavior (no credentials → fallback) ─────────────────────────────

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
    assert "VERIFIED" in r.stdout
    # Earn side: $0.50 inbound
    assert "Inbound:   $0.50" in r.stdout


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
    # Also strip Modal creds to make sure refusal comes from live-mode check.
    env.pop("MODAL_TOKEN_ID", None)
    env.pop("MODAL_TOKEN_SECRET", None)
    r = subprocess.run(
        CLI, capture_output=True, text=True, timeout=30, env=env,
    )
    assert r.returncode != 0
    assert "test mode" in r.stderr.lower() or "refusing" in r.stderr.lower()


def test_earn_and_buy_no_credentials_required():
    """The command must work with NO env vars, NO Stripe key, NO Twilio key, NO Modal key."""
    env = {
        k: v for k, v in os.environ.items()
        if not any(
            kw in k.upper()
            for kw in ("STRIPE", "TWILIO", "OPENAI", "NVIDIA", "NIM", "MODAL")
        )
    }
    r = subprocess.run(
        CLI, capture_output=True, text=True, timeout=30, env=env,
    )
    assert r.returncode == 0, f"failed without creds: {r.stderr}"
    assert "CYCLE COMPLETE" in r.stdout


# ── Fallback path: explicit assertions for the no-creds flow ──────────────────

def test_earn_and_buy_fallback_path_shows_modal_job_name():
    """Without MODAL_TOKEN_ID, step [3/4] should still name the Modal job."""
    r = _run()
    assert "custodian-benchmark.run_benchmark" in r.stdout


def test_earn_and_buy_fallback_path_shows_credential_notice():
    """Without MODAL_TOKEN_ID, the output must include the notice string."""
    r = _run()
    assert "MODAL_TOKEN_ID not configured" in r.stdout


def test_earn_and_buy_fallback_path_exits_zero():
    """The fallback path must complete cleanly and exit 0."""
    r = _run()
    assert r.returncode == 0, (
        f"fallback path exited {r.returncode}\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )


# ── Real-Modal path: mocked registry returns a fake Modal response ───────────

def test_earn_and_buy_with_mocked_modal_uses_real_billed_amount():
    """When the registry returns a real Modal result, the verifier proves
    the actual billed amount (not a hardcoded $0.50)."""
    fake_modal_response = {
        "ok": True,
        "result": {
            "ok": True,
            "elapsed_s": 9.4,
            "gflops": 214.0,
            "billed_usd": 0.002131,
            "device": "cuda",
        },
    }

    env = os.environ.copy()
    env["MODAL_TOKEN_ID"] = "fake-id"
    env["MODAL_TOKEN_SECRET"] = "fake-secret"
    env.pop("CUSTODIAN_STRIPE_LIVE", None)

    # We import cmd_earn_and_buy in-process and patch default_registry to
    # return a stub whose .run() returns the fake Modal response. This
    # exercises the full verification path (including claim.asserted
    # adjustment and ledger.outbound_usd) without making a real network
    # call.
    with patch(
        "custodian.cli.cmd_earn_and_buy._call_modal_benchmark",
        return_value=fake_modal_response,
    ):
        from custodian.cli import cmd_earn_and_buy
        from io import StringIO
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_earn_and_buy.run(args=None)

    out = buf.getvalue()
    assert "CYCLE COMPLETE" in out
    # The verifier line should mention the real billed amount.
    assert "VERIFIED" in out
    assert "0.002131" in out
    # The fallback notice should NOT appear (creds are set).
    assert "MODAL_TOKEN_ID not configured" not in out
    # The Modal job name should still be there.
    assert "custodian-benchmark.run_benchmark" in out
    # The kernel gating should name the Modal tool, not api.nvidia.com.
    assert "modal-invoke" in out
    assert "api.nvidia.com" not in out


def test_earn_and_buy_with_mocked_modal_demo_cap_refused():
    """When the Modal function returns ok=False / reason='demo_cap',
    the spend phase should still complete and the verdict should be
    honest about the refusal."""
    fake_refusal = {
        "ok": True,
        "result": {
            "ok": False,
            "reason": "demo_cap",
            "elapsed_s": 0.0,
            "gflops": 0.0,
            "billed_usd": 0.0,
            "device": "stub",
            "message": "exceeds $0.10 demo cap",
        },
    }

    with patch(
        "custodian.cli.cmd_earn_and_buy._call_modal_benchmark",
        return_value=fake_refusal,
    ):
        from custodian.cli import cmd_earn_and_buy
        from io import StringIO
        import contextlib

        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_earn_and_buy.run(args=None)

    out = buf.getvalue()
    # The refusal should be visible on camera so the verifier verdict
    # reflects what actually happened. (The output uses "REFUSED:" and
    # the human-readable message; the raw "demo_cap" reason is in the
    # upstream dict but the CLI doesn't echo it.)
    assert "REFUSED" in out
    assert "exceeds $0.10 demo cap" in out
    # Even when the Modal call is refused, the earn-and-buy cycle still
    # exits 0 — the refusal is itself the verified result.
    assert "CYCLE COMPLETE" in out


# ── Registry helper: the new ToolRegistry.run() method ───────────────────────

def test_tool_registry_run_invokes_tool():
    """ToolRegistry.run(name, **kwargs) is the helper cmd_earn_and_buy uses."""
    from custodian.tools.registry import default_registry

    reg = default_registry().load()
    # modal-invoke should be registered.
    assert reg.get("modal-invoke") is not None

    # Unknown tool returns a structured error (no raise).
    result = reg.run("nonexistent-tool-xyz")
    assert result["ok"] is False
    assert "not found" in result.get("error", "")
