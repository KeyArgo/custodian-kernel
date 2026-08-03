"""Unit tests for Custodian's opt-in, no-network Bubblewrap profile."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from custodian.exceptions import ToolSandboxUnavailableError
from custodian import sandbox


def test_confined_profile_has_kernel_network_isolation_and_minimal_mounts(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: "/usr/bin/bwrap")
    skill_dir = tmp_path / "skill"
    workspace = tmp_path / "workspace"
    skill_dir.mkdir()
    workspace.mkdir()

    argv = sandbox.build_confined_argv(
        ["/usr/bin/python3", str(skill_dir / "execute.py")],
        workspace=str(workspace), ro_dirs=[str(skill_dir)],
    )

    assert "--unshare-net" in argv
    assert "--clearenv" in argv
    assert ["--bind", str(workspace.resolve()), str(workspace.resolve())] == (
        argv[argv.index("--bind"):argv.index("--bind") + 3]
    )
    assert ["--ro-bind", str(skill_dir.resolve()), str(skill_dir.resolve())] == (
        argv[argv.index(str(skill_dir.resolve())) - 1:argv.index(str(skill_dir.resolve())) + 2]
    )
    assert ["--ro-bind", "/", "/"] not in [argv[index:index + 3] for index in range(len(argv) - 2)]
    assert argv[argv.index("--chdir") + 1] == str(workspace.resolve())
    assert ["--ro-bind-try", "/proc/sys", "/proc/sys"] in [
        argv[index:index + 3] for index in range(len(argv) - 2)
    ]
    if Path("/proc/sysrq-trigger").exists():
        assert ["--ro-bind-try", "/dev/null", "/proc/sysrq-trigger"] in [
            argv[index:index + 3] for index in range(len(argv) - 2)
        ]


@pytest.mark.parametrize("workspace", ["", "/"])
def test_confined_profile_rejects_missing_or_broad_workspace(workspace, monkeypatch):
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: "/usr/bin/bwrap")
    with pytest.raises(ToolSandboxUnavailableError):
        sandbox.build_confined_argv(["/bin/true"], workspace=workspace)


def test_confined_profile_rejects_home_workspace(monkeypatch):
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: "/usr/bin/bwrap")
    with pytest.raises(ToolSandboxUnavailableError):
        sandbox.build_confined_argv(["/bin/true"], workspace=str(Path.home()))


def test_require_confined_profile_never_has_an_unsandboxed_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "confined_sandbox_available", lambda: False)
    with pytest.raises(ToolSandboxUnavailableError, match="cannot build a confined"):
        sandbox.require_confined_argv(["/bin/true"], workspace=str(tmp_path))


@pytest.mark.skipif(
    not sandbox.confined_sandbox_available(),
    reason="confined profile requires Bubblewrap with unprivileged network namespaces",
)
def test_confined_profile_only_writes_its_workspace_and_has_no_network(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "host-secret.txt"
    workspace.mkdir()
    outside.write_text("host-only")
    script = (
        "from pathlib import Path; import socket; "
        f"outside = Path({str(outside)!r}); workspace = Path({str(workspace)!r}); "
        "assert not outside.exists(); "
        "(workspace / 'sandbox-output.txt').write_text('ok'); "
        "sock = socket.socket(); "
        "assert sock.connect_ex(('1.1.1.1', 443)) != 0"
    )
    system_python = shutil.which("python3", path="/usr/local/bin:/usr/bin:/bin")
    assert system_python, "confined runtime requires a system python3"
    result = subprocess.run(
        sandbox.require_confined_argv(
            [system_python, "-c", script], workspace=str(workspace),
        ),
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert (workspace / "sandbox-output.txt").read_text() == "ok"
    assert outside.read_text() == "host-only"
