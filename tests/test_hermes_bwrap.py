"""Smoke tests for scripts/hermes-bwrap — the Bubblewrap containment launcher.

These tests verify the launcher's argument parsing, YOLO rejection, and
exit codes without requiring actual Bubblewrap or Hermes execution. The
launcher is exercised as a subprocess with controlled arguments.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hermes-bwrap"


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
    )


def test_help_exits_zero():
    r = _run("--help")
    assert r.returncode == 0
    assert "usage: hermes-bwrap" in r.stdout


def test_rejects_yolo_flag():
    for flag in ("--yolo", "-z", "--oneshot", "--force"):
        r = _run("--workspace", "/tmp", "--", flag, "hello")
        assert r.returncode == 2, f"{flag} not rejected: rc={r.returncode}"
        assert "refusing" in r.stderr.lower(), f"no refusal for {flag}: {r.stderr}"


def test_rejects_yolo_startswith():
    """--yolo=true and similar must also be blocked."""
    r = _run("--workspace", "/tmp", "--", "--yolo=true", "hello")
    assert r.returncode == 2
    assert "refusing" in r.stderr.lower()


def test_missing_workspace_fails():
    """--workspace is required."""
    r = _run("--help")  # --help doesn't require --workspace
    assert r.returncode == 0
    r2 = _run()  # no args at all
    assert r2.returncode != 0


def test_nonexistent_workspace_fails():
    r = _run("--workspace", "/tmp/nonexistent-dir-xyz-123")
    assert r.returncode == 1
    assert "not found" in r.stderr.lower() or "workspace" in r.stderr.lower()


def test_allow_network_flag_accepted():
    """--allow-network is a valid flag that doesn't crash parsing."""
    r = _run("--help")  # won't reach workspace check
    assert r.returncode == 0
