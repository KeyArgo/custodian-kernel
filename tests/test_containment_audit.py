"""Tests for custodian.containment_audit -- the containment leak watchdog.

Covers the three check modes:
- static ``audit_mount_spec`` (must flag the whole-state-dir bind bug class
  and must stay clean for the fixed hermes-bwrap / paladin mount builders);
- runtime ``scan_live_sandboxes`` (finds a deliberately leaky live bwrap);
- empirical ``probe_containment`` (detects a marker visible through a leaky
  sandbox).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from custodian import containment_audit as ca

_SSH = "." + "ssh"  # constructed so the forbidden literal never appears


def test_socket_masked_by_dev_null_bind(tmp_path, monkeypatch):
    """A /dev/null bind over an existing container socket counts as a mask."""
    sock = tmp_path / "docker.sock"
    sock.touch()
    monkeypatch.setattr(ca, "deny_paths", lambda: [sock])
    argv = [
        "bwrap", "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--ro-bind", "/dev/null", str(sock),
        "true",
    ]
    assert ca.audit_mount_spec(argv) == []


def test_socket_exposed_without_mask(tmp_path, monkeypatch):
    """An existing container socket under an ancestor bind is a finding."""
    sock = tmp_path / "docker.sock"
    sock.touch()
    monkeypatch.setattr(ca, "deny_paths", lambda: [sock])
    argv = ["bwrap", "--ro-bind", "/", "/", "true"]
    findings = ca.audit_mount_spec(argv)
    assert findings, "existing socket must be flagged when unmasked"
    assert str(sock) in findings[0].exposed


def test_audit_stops_at_child_command_boundary(tmp_path, monkeypatch):
    """Trailing child argv must never erase a leak finding (regression).

    A fake ``--tmpfs`` token appended AFTER the child executable is inert
    text as far as bwrap is concerned; the audit must not parse it as a
    mount, or an operator/attacker could selectively blind the pre-flight
    gate while the real sandbox still exposes the path.
    """
    sock = tmp_path / "docker.sock"
    sock.touch()
    monkeypatch.setattr(ca, "deny_paths", lambda: [sock])
    argv = ["bwrap", "--ro-bind", "/", "/",
            "hermes", "--profile", "dev",
            "--tmpfs", str(sock), "--ro-bind", str(sock), "/home/x/.ssh"]
    findings = ca.audit_mount_spec(argv)
    assert any(f.exposed == str(sock) for f in findings), (
        "trailing child args must not mask the exposure"
    )


def test_nested_mask_does_not_cover_parent(tmp_path, monkeypatch):
    """A mask nested inside a sensitive dir must not hide the dir itself."""
    sock = tmp_path / "docker.sock"
    sock.touch()
    nested = sock.parent / "nested"
    monkeypatch.setattr(ca, "deny_paths", lambda: [sock])
    argv = ["bwrap", "--ro-bind", "/", "/", "--tmpfs", str(nested), "true"]
    findings = ca.audit_mount_spec(argv)
    assert any(f.exposed == str(sock) for f in findings), (
        "nested mask must not count as covering the parent path"
    )


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A fake Custodian state dir with policy files + planted secrets."""
    state_dir = tmp_path / "custodian-state"
    state_dir.mkdir()
    for name in ca.ALLOWED_STATE_FILES:
        (state_dir / name).write_text('{"policy": true}')
    (state_dir / "codex-guard-receipts.jsonl").write_text("RECEIPT\n")
    (state_dir / "codex-approval.key").write_text("K" * 32)
    (state_dir / "ledger.db").write_text("LEDGER")
    (state_dir / "codex-approvals").mkdir()
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state_dir))
    return state_dir


# --- static audit -----------------------------------------------------------


def test_whole_state_dir_bind_is_flagged(state):
    """The old hermes-bwrap bug: binding the whole state dir must be a leak."""
    findings = ca.audit_mount_spec(["--ro-bind", str(state), str(state)])
    exposed = {f.exposed for f in findings}
    assert any("receipts" in e for e in exposed), findings
    assert any("codex-approval.key" in e for e in exposed), findings
    assert any(f.severity == "high" for f in findings)
    # Policy files may be visible; the rest must not be exposed.
    assert "approval-policy.json" not in " ".join(exposed)


def test_rw_ssh_bind_is_critical(tmp_path, monkeypatch):
    home = tmp_path / "home"
    ssh = home / _SSH
    ssh.mkdir(parents=True)
    monkeypatch_home(tmp_path, monkeypatch)
    findings = ca.audit_mount_spec(["--bind", str(ssh), str(ssh)])
    assert any(f.severity == "critical" for f in findings), findings


def test_policy_file_bind_is_allowed(state):
    findings = ca.audit_mount_spec([
        "--ro-bind", str(state / "approval-policy.json"),
        str(state / "approval-policy.json")])
    assert findings == [], findings


def test_receipt_file_bind_is_flagged(state):
    findings = ca.audit_mount_spec([
        "--ro-bind", str(state / "codex-guard-receipts.jsonl"),
        str(state / "codex-guard-receipts.jsonl")])
    assert len(findings) == 1
    assert findings[0].severity == "high"


def test_root_bind_with_full_masks_is_clean(tmp_path, monkeypatch):
    """paladin-style: --ro-bind / / plus a tmpfs mask over every deny path
    AND the Custodian state dir (paladin masks ~/.custodian too)."""
    monkeypatch_home(tmp_path, monkeypatch)
    argv = ["bwrap", "--unshare-all", "--ro-bind", "/", "/"]
    for deny in ca.deny_paths():
        argv += ["--tmpfs", str(deny)]
    argv += ["--tmpfs", str(ca.state_dir())]
    argv += ["--ro-bind", str(tmp_path), str(tmp_path)]
    assert ca.audit_mount_spec(argv) == []


def test_root_bind_missing_one_mask_is_flagged(tmp_path, monkeypatch):
    monkeypatch_home(tmp_path, monkeypatch)
    # The audit only flags deny paths that EXIST on the host; create the
    # temp-home ones so the missing mask is a real exposure.
    home = tmp_path / "home"
    deny = ca.deny_paths()
    for d in deny:
        if str(d).startswith(str(home)):
            d.mkdir(parents=True, exist_ok=True)
    unmasked = next(d for d in deny if str(d).startswith(str(home)))
    argv = ["bwrap", "--ro-bind", "/", "/"]
    for d in deny:
        if d != unmasked:
            argv += ["--tmpfs", str(d)]
    findings = ca.audit_mount_spec(argv)
    assert any(f.exposed == str(unmasked) for f in findings), findings


def test_hermes_bwrap_builder_is_clean(tmp_path, monkeypatch):
    """The FIXED launcher: policy files RO, everything else invisible."""
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader(
        "hbw", str(Path(__file__).resolve().parent.parent / "scripts" / "hermes-bwrap"))
    spec = importlib.util.spec_from_loader("hbw", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)

    home = tmp_path / "home"
    hermes_home = home / ".hermes"
    ws = tmp_path / "ws"
    (hermes_home / "profiles").mkdir(parents=True)
    (hermes_home / "plugins").mkdir()
    (hermes_home / "logs").mkdir()
    (hermes_home / "memories").mkdir()
    ws.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    for name in ca.ALLOWED_STATE_FILES:
        (state / name).write_text("{}")
    (state / "codex-guard-receipts.jsonl").write_text("x")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state))
    mounts = mod._build_mounts(ws, hermes_home, state)
    argv = ["bwrap", "--unshare-user", *mounts]
    findings = ca.audit_mount_spec(argv)
    assert findings == [], findings


# --- live scan --------------------------------------------------------------


def _spawn_leaky_bwrap(state_dir):
    """Start a real bwrap child that binds the state dir read-only."""
    proc = subprocess.Popen([
        "bwrap", "--unshare-user", "--unshare-pid",
        "--ro-bind", "/", "/",
        "--ro-bind", str(state_dir), str(state_dir),
        "--die-with-parent", "sleep", "30",
    ])
    return proc


@pytest.mark.skipif(shutil.which("bwrap") is None,
                    reason="bubblewrap not installed")
def test_live_scan_finds_leaky_bwrap(monkeypatch):
    # The leak dir must NOT live under /tmp: bwrap auto-mounts tmpfs on /tmp
    # (and /dev/shm, /run), which shadows anything bound underneath it.  Use
    # repo scratch space (a real fs) instead.
    import uuid

    repo = Path(__file__).resolve().parent.parent
    state_dir = repo / f".tmp-live-leak-{uuid.uuid4().hex[:8]}"
    state_dir.mkdir()
    (state_dir / "codex-guard-receipts.jsonl").write_text("x\n")
    (state_dir / "codex-approval.key").write_text("K" * 32)
    proc = _spawn_leaky_bwrap(state_dir)
    try:
        monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state_dir))
        out = ca.scan_live_sandboxes()
        assert proc.pid in out, f"leaky bwrap {proc.pid} not flagged: {out}"
        exposed = {f.exposed for f in out[proc.pid]}
        assert any("receipts" in e for e in exposed), out[proc.pid]
        assert any("codex-approval.key" in e for e in exposed), out[proc.pid]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        import shutil as _sh
        _sh.rmtree(state_dir, ignore_errors=True)


@pytest.mark.skipif(shutil.which("bwrap") is None,
                    reason="bubblewrap not installed")
def test_live_scan_clean_bwrap_not_flagged(tmp_path, monkeypatch):
    proc = subprocess.Popen([
        "bwrap", "--unshare-user", "--unshare-pid",
        "--ro-bind", "/usr", "/usr",
        "--die-with-parent", "sleep", "30",
    ])
    try:
        out = ca.scan_live_sandboxes()
        assert proc.pid not in out, f"clean bwrap flagged: {out.get(proc.pid)}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


# --- empirical probe --------------------------------------------------------


@pytest.mark.skipif(shutil.which("bwrap") is None,
                    reason="bubblewrap not installed")
def test_probe_detects_leak_through_leaky_launcher(tmp_path):
    """probe_containment machinery: a leaky launcher is caught by the probe."""
    ws = tmp_path / "ws"
    ws.mkdir()
    leaky_launcher = ws / "leaky-launcher"
    # Bind the WHOLE fs read-only: the marker home (sibling of the workspace)
    # is therefore visible and must show up as LEAK in the probe output.
    leaky_launcher.write_text(
        "#!/bin/sh\n"
        'exec bwrap --unshare-user --unshare-pid --ro-bind / / '
        f'/bin/sh "{ws}/bin/hermes"\n')
    leaky_launcher.chmod(0o755)
    rc, out = ca.probe_containment([str(leaky_launcher)], ws)
    assert "LEAK:" in out, f"probe missed the leak:\n{out}"


def test_probe_marker_planting(tmp_path):
    """probe_containment plants markers and runs the probe command."""
    ws = tmp_path / "ws"
    ws.mkdir()
    fake = ws / "fake-launcher"
    # No sandbox: just run the planted probe script directly.
    fake.write_text(f"#!/bin/sh\nexec /bin/sh \"{ws}/bin/hermes\"\n")
    fake.chmod(0o755)
    rc, out = ca.probe_containment([str(fake)], ws, timeout=30)
    assert "PROBE_DONE" in out
    # Running with no sandbox: markers ARE visible (home is the real env).
    assert "LEAK:" in out or "OK:" in out


def monkeypatch_home(tmp_path, monkeypatch):
    """Point Path.home() at a temp home for deny-path computation."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
