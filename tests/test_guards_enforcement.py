"""The gate must be a real control, not just status metadata.

These tests prove that the codex/claude/hermes guard hooks each consult
``custodian.guards.gate.is_enabled`` before making a decision, and that
a disabled guard costs the operator nothing (passes through, no
receipts, no enforcement).

Regression for the post-Codex sign-off finding: "No reviewed hook code
consumes ``is_enabled()``."
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _state_dir(tmp_path: Path, monkeypatch) -> str:
    s = str(tmp_path / "state")
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", s)
    return s


def test_codex_hook_defer_when_disabled(tmp_path, monkeypatch):
    """Disabled codex guard → hook emits defer (no payload), not deny."""
    _state_dir(tmp_path, monkeypatch)
    result = subprocess.run(
        [sys.executable, "-m", "custodian.guards.codex.hook"],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # Codex's defer contract is "emit nothing on stdout so the harness's
    # own approval flow proceeds". So: empty stdout, no permissionDecision
    # set, and definitely no deny.
    if result.stdout.strip():
        payload = json.loads(result.stdout)
        decision = payload.get("hookSpecificOutput", {}).get("permissionDecision")
        assert decision != "deny", f"disabled guard should not deny; got {decision!r}"


def test_claude_hook_defer_when_disabled(tmp_path, monkeypatch):
    """Disabled claude guard → hook emits defer, not deny, and exits 0."""
    _state_dir(tmp_path, monkeypatch)
    result = subprocess.run(
        [sys.executable, "-m", "custodian.guards.claude.hook"],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    if result.stdout.strip():
        payload = json.loads(result.stdout)
        decision = payload.get("decision") or payload.get("hookSpecificOutput", {}).get("permissionDecision")
        assert decision != "deny", f"disabled guard should not deny; got {decision!r}"


def test_codex_hook_denies_when_enabled(tmp_path, monkeypatch):
    """Enabled codex guard → hook must still make a real decision.

    The default policy denies obvious high-risk commands; this test
    proves enabling the guard actually arms enforcement, not just
    changes the status report."""
    s = _state_dir(tmp_path, monkeypatch)
    from custodian.guards.gate import enable
    enable(s, "codex")
    result = subprocess.run(
        [sys.executable, "-m", "custodian.guards.codex.hook"],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    # With the codex guard enabled, the default policy denies this. The
    # important assertion is that the gate made a difference: a disabled
    # guard (test above) returned non-deny; an enabled guard returns deny
    # for this dangerous input.
    payload = json.loads(result.stdout)
    decision = payload.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny", (
        f"enabled codex guard must deny rm -rf /; got {decision!r}; "
        "this proves the gate is a real control, not metadata"
    )


def test_hermes_runtime_refuses_to_construct_when_disabled(tmp_path, monkeypatch):
    """Hermes guard runtime raises DisabledGuardError when the gate is off."""
    _state_dir(tmp_path, monkeypatch)
    from custodian.guards.hermes.runtime import HermesGuardRuntime, _DisabledGuardError
    with pytest.raises(_DisabledGuardError):
        HermesGuardRuntime()


def test_hermes_runtime_constructs_when_enabled(tmp_path, monkeypatch):
    """When the hermes guard is enabled, the runtime constructs normally."""
    s = _state_dir(tmp_path, monkeypatch)
    from custodian.guards.gate import enable
    enable(s, "hermes")
    from custodian.guards.hermes.runtime import HermesGuardRuntime
    rt = HermesGuardRuntime()
    assert rt is not None


# late import for pytest
import pytest
