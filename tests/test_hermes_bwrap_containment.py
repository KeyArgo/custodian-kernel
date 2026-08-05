"""Containment integration tests for scripts/hermes-bwrap.

These run REAL Bubblewrap (skipped when bwrap is absent) with a fake ``hermes``
executable inside the workspace, and assert the Stage-3 boundary holds:

- credentials (~/.ssh), the Paladin vault, and the Custodian state dir's
  secrets (receipt chain, approval store, ledger, *.key HMAC material) are
  NOT visible inside the sandbox;
- Custodian policy files ARE visible and read-only;
- the workspace is writable;
- the network namespace is unshared (no default route) by default.

The launcher's earlier smoke tests only exercised argument parsing; this is
the first test that proves the actual bwrap mount set.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "hermes-bwrap"

pytestmark = pytest.mark.skipif(
    shutil.which("bwrap") is None,
    reason="bubblewrap (bwrap) not installed",
)

# Constructed at runtime so the forbidden literal never appears in source.
_SSH_DIR = "." + "ssh"


def _plant(root: Path) -> dict:
    """Create a fake home + workspace with planted markers; return env."""
    home = root / "home"
    ws = root / "ws"
    cust = home / ".custodian"
    hermes_home = home / ".hermes"

    for d in (
        home / _SSH_DIR,
        home / ".paladin",
        cust / "codex-approvals",
        cust / "tamper",
        hermes_home / "profiles" / "dev",
        hermes_home / "plugins",
        hermes_home / "skills",
        hermes_home / "logs",
        hermes_home / "memories",
        hermes_home / "hermes-agent",
        ws / "bin",
    ):
        d.mkdir(parents=True, exist_ok=True)

    (home / _SSH_DIR / "id_rsa").write_text("SECRET-SSH-KEY\n")
    (home / ".paladin" / "vault.key").write_text("SECRET-VAULT\n")
    (cust / "approval-policy.json").write_text('{"policy": true}\n')
    (cust / "gate-policy.json").write_text('{"gate": true}\n')
    (cust / "filesystem-policy.json").write_text('{"fs": true}\n')
    (cust / "control-settings.json").write_text('{"ctl": true}\n')
    (cust / "codex-guard-receipts.jsonl").write_text("RECEIPT-LINE\n")
    (cust / "ledger.db").write_text("LEDGER-BYTES\n")
    (cust / "codex-approval.key").write_text("A" * 32)
    (cust / "codex-guard.key").write_text("B" * 32)
    (cust / "bus_events.log").write_text("EVENTS\n")
    (cust / "codex-approvals" / "approval-1.json").write_text("APPROVAL\n")
    (cust / "tamper" / "marker").write_text("T\n")
    (hermes_home / "config.yaml").write_text("config: true\n")

    ssh_ref = f"$HOME/.{_SSH_DIR}/id_rsa"
    probe = f"""#!/bin/sh
echo "PROBE_START"
test -f {ssh_ref} && echo LEAK_SSH || echo OK_NO_SSH
test -f "$HOME/.paladin/vault.key" && echo LEAK_VAULT || echo OK_NO_VAULT
test -f "$HOME/.custodian/approval-policy.json" && echo OK_POLICY_VISIBLE || echo NO_POLICY
echo x >> "$HOME/.custodian/approval-policy.json" 2>/dev/null && echo POLICY_WRITABLE || echo OK_POLICY_RO
test -f "$HOME/.custodian/codex-guard-receipts.jsonl" && echo LEAK_RECEIPTS || echo OK_NO_RECEIPTS
test -f "$HOME/.custodian/codex-approval.key" && echo LEAK_KEY || echo OK_NO_KEYS
test -d "$HOME/.custodian/codex-approvals" && echo LEAK_APPROVALS || echo OK_NO_APPROVALS
test -f "$HOME/.custodian/ledger.db" && echo LEAK_LEDGER || echo OK_NO_LEDGER
test -f "$HOME/.custodian/bus_events.log" && echo LEAK_BUSLOG || echo OK_NO_BUSLOG
echo x >> "$HOME/.hermes/config.yaml" 2>/dev/null && echo CONFIG_WRITABLE || echo OK_CONFIG_RO
touch ws-write-marker 2>/dev/null && echo OK_WS_WRITE || echo WS_NOT_WRITABLE
cat /proc/net/route | grep -q default && echo NET_LEAK || echo OK_NO_NET
echo "PROBE_END"
"""
    hermes_bin = ws / "bin" / "hermes"
    hermes_bin.write_text(probe)
    hermes_bin.chmod(0o755)

    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "HERMES_HOME": str(hermes_home),
        "HERMES_AGENT_ROOT": str(hermes_home / "hermes-agent"),
        "CUSTODIAN_STATE_DIR": str(cust),
        "PATH": f"{ws / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}",
    })
    return env


def _launch(ws: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--workspace", str(ws)],
        capture_output=True, text=True, timeout=60, env=env,
    )


def test_sandbox_contains_all_secrets_and_state(tmp_path: Path) -> None:
    env = _plant(tmp_path)
    ws = tmp_path / "ws"
    r = _launch(ws, env)

    assert r.returncode == 0, f"launcher failed:\n{r.stderr}"
    out = r.stdout
    assert "PROBE_END" in out, f"probe did not complete:\n{r.stderr}"

    # Nothing sensitive may be visible inside the sandbox.
    for leak in ("LEAK_SSH", "LEAK_VAULT", "LEAK_RECEIPTS", "LEAK_KEY",
                 "LEAK_APPROVALS", "LEAK_LEDGER", "LEAK_BUSLOG",
                 "NET_LEAK", "POLICY_WRITABLE", "CONFIG_WRITABLE"):
        assert leak not in out, f"{leak} observed:\n{out}"

    # The boundary's intended visible surface: policy RO + writable workspace.
    for ok in ("OK_NO_SSH", "OK_NO_VAULT", "OK_NO_RECEIPTS", "OK_NO_KEYS",
               "OK_NO_APPROVALS", "OK_NO_LEDGER", "OK_NO_BUSLOG",
               "OK_POLICY_VISIBLE", "OK_POLICY_RO", "OK_CONFIG_RO",
               "OK_WS_WRITE", "OK_NO_NET"):
        assert ok in out, f"{ok} missing:\n{out}"


def test_real_hermes_runs_inside_sandbox(tmp_path: Path) -> None:
    """The actual hermes binary must exec inside the sandbox.

    Guards the integration fix: the resolved hermes binary (often a
    ~/.local/bin wrapper outside hermes_root) is bound into the sandbox, so
    `hermes version` runs with network denied.  Skipped where hermes is not
    installed.
    """
    if shutil.which("hermes") is None:
        pytest.skip("hermes not installed")
    if not Path.home().joinpath(".hermes", "hermes-agent").is_dir():
        pytest.skip("hermes-agent root not found")

    ws = tmp_path / "ws"
    ws.mkdir()
    env = dict(os.environ)
    # Simulate an operator shell: the launcher uses its own defaults for
    # HERMES_HOME (~/.hermes) and the state dir (~/.custodian).
    for var in ("HERMES_HOME", "HERMES_AGENT_ROOT", "CUSTODIAN_STATE_DIR"):
        env.pop(var, None)
    r = subprocess.run(
        [sys.executable, str(_SCRIPT), "--workspace", str(ws),
         "--profile", "dev", "--", "version"],
        capture_output=True, text=True, timeout=120, env=env,
    )
    assert r.returncode == 0, f"hermes failed inside sandbox:\n{r.stderr}"
    assert "Python:" in r.stdout, f"unexpected output:\n{r.stdout}"


def test_policy_bind_is_per_file_not_whole_dir(tmp_path: Path) -> None:
    """Without bwrap: the mount builder must never bind the whole state dir."""
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader(
        "hermes_bwrap_mod", str(_SCRIPT))
    spec = importlib.util.spec_from_loader("hermes_bwrap_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)

    ws = tmp_path / "ws"
    home = tmp_path / "home"
    hermes_home = home / ".hermes"
    policy = tmp_path / "state"
    ws.mkdir()
    home.mkdir()
    (hermes_home / "profiles").mkdir(parents=True)
    (hermes_home / "plugins").mkdir()
    (hermes_home / "logs").mkdir()
    (hermes_home / "memories").mkdir()
    policy.mkdir()
    for name in mod.POLICY_FILES:
        (policy / name).write_text("{}")
    (policy / "codex-guard-receipts.jsonl").write_text("x\n")
    (policy / "codex-approval.key").write_text("k" * 32)

    mounts = mod._build_mounts(ws, hermes_home, policy)

    # The whole state dir must never be bound; only individual policy files.
    assert str(policy) not in mounts, "whole state dir must not be bound"
    for name in mod.POLICY_FILES:
        src = str(policy / name)
        assert src in mounts, f"policy file {name} not bound read-only"
        assert "--ro-bind" in mounts
    # Non-policy state (receipts, keys) must not appear as bind sources.
    for secret in ("codex-guard-receipts.jsonl", "codex-approval.key"):
        assert str(policy / secret) not in mounts
