"""Red-team corpus for custodian/sandbox.py's filesystem/exec confinement.

Each test here proves a specific claim about what the bwrap wrapper
actually stops, not just that it doesn't break legitimate calls (that's
covered by the ordinary CustodianTool.invoke() tests in test_tools.py).
Skipped outright on a host where bwrap or unprivileged user namespaces
aren't available, since there is nothing real to red-team there.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from custodian.exceptions import ToolSandboxUnavailableError
from custodian.sandbox import (
    build_sandboxed_argv,
    require_sandboxed_argv,
    sandbox_available,
)

pytestmark = pytest.mark.skipif(
    not sandbox_available(),
    reason="bwrap or unprivileged user namespaces unavailable on this host",
)


def _run_script(tmp_path: Path, body: str, *, rw_dirs=(), timeout=15) -> dict:
    script = tmp_path / "probe.py"
    script.write_text(body)
    argv = build_sandboxed_argv([sys.executable, str(script)], rw_dirs=rw_dirs)
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return json.loads(proc.stdout.strip())


def test_sensitive_home_dir_reads_as_empty(tmp_path, monkeypatch):
    """~/.ssh must read empty inside the sandbox even though the real file
    exists on the host with real secret content."""
    monkeypatch.setenv("HOME", str(tmp_path))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_rsa").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nreal-secret\n")

    result = _run_script(tmp_path, """
import json, os
p = os.path.expanduser("~/.ssh/id_rsa")
seen = os.path.exists(p)
content = open(p).read() if seen else None
print(json.dumps({"ok": True, "seen": seen, "content": content}))
""")
    assert result["seen"] is False
    assert result["content"] is None


def test_cannot_write_outside_declared_rw_dirs(tmp_path):
    """The base filesystem bind is read-only -- a script may only write
    inside directories explicitly passed as rw_dirs."""
    outside = tmp_path / "outside"
    outside.mkdir()
    rw = tmp_path / "allowed"
    rw.mkdir()

    result = _run_script(tmp_path, f"""
import json
ok = False
try:
    with open({str(outside / "pwned.txt")!r}, "w") as f:
        f.write("owned")
    ok = True
except OSError as e:
    err = str(e)
print(json.dumps({{"ok": ok, "err": locals().get("err")}}))
""", rw_dirs=[str(rw)])
    assert result["ok"] is False
    assert "Read-only file system" in result["err"] or "Permission denied" in result["err"]


def test_can_write_inside_declared_rw_dir(tmp_path):
    """The positive case: an rw_dir really is writable, proving the
    read-only failure above is about confinement, not a broken sandbox."""
    rw = tmp_path / "allowed"
    rw.mkdir()

    result = _run_script(tmp_path, f"""
import json
with open({str(rw / "note.txt")!r}, "w") as f:
    f.write("hello")
print(json.dumps({{"ok": True}}))
""", rw_dirs=[str(rw)])
    assert result["ok"] is True
    assert (rw / "note.txt").read_text() == "hello"


def test_cannot_see_processes_outside_the_sandbox_pid_namespace():
    """--unshare-pid means the sandboxed process's own /proc only shows
    its own process tree, not the host's."""
    argv = build_sandboxed_argv([sys.executable, "-c",
        "import json,os; print(json.dumps({'pids': os.listdir('/proc')}))"])
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    result = json.loads(proc.stdout.strip())
    numeric_pids = [p for p in result["pids"] if p.isdigit()]
    # Only itself (and possibly bwrap's own pid-1 shim) should be visible --
    # a host with hundreds of real processes running would show all of them
    # without namespace isolation.
    assert len(numeric_pids) <= 2


def test_require_sandboxed_argv_wraps_with_bwrap():
    argv = require_sandboxed_argv(["/bin/true"])
    assert argv[0].endswith("bwrap")
    assert "/bin/true" in argv


def test_require_sandboxed_argv_fails_closed_when_unavailable(monkeypatch):
    import custodian.sandbox as sandbox_mod
    monkeypatch.setattr(sandbox_mod, "sandbox_available", lambda: False)
    with pytest.raises(ToolSandboxUnavailableError):
        require_sandboxed_argv(["/bin/true"])


def test_require_sandboxed_argv_allows_opt_out_when_unavailable(monkeypatch):
    import custodian.sandbox as sandbox_mod
    monkeypatch.setattr(sandbox_mod, "sandbox_available", lambda: False)
    argv = require_sandboxed_argv(["/bin/true"], allow_unsandboxed=True)
    assert argv == ["/bin/true"]


def test_unsandboxed_prints_deprecation_banner(monkeypatch, capsys):
    """allow_unsandboxed=True prints a DEPRECATED banner to stderr."""
    import custodian.sandbox as sandbox_mod
    monkeypatch.setattr(sandbox_mod, "sandbox_available", lambda: False)
    require_sandboxed_argv(["/bin/true"], allow_unsandboxed=True)
    captured = capsys.readouterr()
    assert "DEPRECATED" in captured.err


def test_unsandboxed_acknowledged_suppresses_banner(monkeypatch, capsys):
    """PALADIN_UNSAFE_ACKNOWLEDGED=1 suppresses the deprecation banner."""
    import custodian.sandbox as sandbox_mod
    monkeypatch.setattr(sandbox_mod, "sandbox_available", lambda: False)
    monkeypatch.setenv("PALADIN_UNSAFE_ACKNOWLEDGED", "1")
    require_sandboxed_argv(["/bin/true"], allow_unsandboxed=True)
    captured = capsys.readouterr()
    assert "DEPRECATED" not in captured.err
