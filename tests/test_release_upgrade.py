"""Network regression for the real broken 0.4.0 -> current release upgrade."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KERNEL_PYPROJECT = ROOT / "packaging/kernel/pyproject.toml"


def _kernel_version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', KERNEL_PYPROJECT.read_text(), re.MULTILINE)
    assert m, f"cannot read version from {KERNEL_PYPROJECT}"
    return m.group(1)


def _checked(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, capture_output=True, text=True,
        encoding="utf-8", errors="replace", **kwargs,
    )
    assert result.returncode == 0, (
        f"command failed ({result.returncode}): {' '.join(command)}\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result


@pytest.mark.network
def test_real_pypi_040_upgrades_to_filtered_041_and_preserves_data(tmp_path):
    release_tree = tmp_path / "release-tree"
    dist = tmp_path / "dist"
    _checked([
        sys.executable, str(ROOT / "scripts/build-kernel-release-tree.py"),
        str(release_tree),
    ], timeout=60)
    _checked([
        sys.executable, "-m", "build", "--wheel", "-o", str(dist),
        str(release_tree),
    ], timeout=300)
    wheels = list(dist.glob(f"custodian_kernel-{_kernel_version()}-*.whl"))
    assert len(wheels) == 1

    environment = tmp_path / "venv"
    venv.create(environment, with_pip=True)
    bin_dir = environment / ("Scripts" if os.name == "nt" else "bin")
    pip = bin_dir / ("pip.exe" if os.name == "nt" else "pip")
    custodian = bin_dir / ("custodian.exe" if os.name == "nt" else "custodian")
    home = tmp_path / "home"
    markers = [
        home / ".custodian/vaults/KEEP",
        home / ".custodian/ledger/KEEP",
        home / ".paladin/KEEP",
        home / ".talaria/KEEP",
    ]
    for marker in markers:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("preserve", encoding="utf-8")
    env = dict(os.environ, HOME=str(home))
    env.pop("PYTHONPATH", None)

    _checked([str(pip), "install", "custodian-kernel==0.4.0"], env=env, timeout=300)
    _checked([str(pip), "install", "--upgrade", str(wheels[0])], env=env, timeout=300)
    version = _checked([str(custodian), "--version"], env=env, timeout=30)
    assert _kernel_version() in version.stdout
    _checked([str(custodian), "console", "--once"], env=env, timeout=30)
    for marker in markers:
        assert marker.read_text(encoding="utf-8") == "preserve"

    # The managed installer must execute the installed command after switching
    # runtimes. A venv can install and pass doctor, yet become unusable if it is
    # renamed afterward because generated shebangs contain absolute paths.
    managed = tmp_path / "managed"
    commands = tmp_path / "commands"
    commands.mkdir()
    installer = release_tree / "install-custodian.py"
    original_launcher = commands / (
        "custodian.cmd" if os.name == "nt" else "custodian"
    )
    original_text = "@echo off\r\necho original\r\n" if os.name == "nt" else "#!/bin/sh\necho original\n"
    # write with newline="" too: write_text() would translate the literal \n
    # to \r\n on Windows, doubling the CR in the CRLF launcher content.
    with original_launcher.open("w", encoding="utf-8", newline="") as fh:
        fh.write(original_text)
    if os.name != "nt":
        original_launcher.chmod(0o755)
    _checked([
        sys.executable, str(installer), "--package", str(wheels[0]),
        "--runtime-root", str(managed), "--bin-dir", str(commands),
    ], env=env, timeout=300)
    managed_custodian = commands / (
        "custodian.cmd" if os.name == "nt" else "custodian"
    )
    managed_version = _checked([str(managed_custodian), "--version"], env=env, timeout=30)
    assert _kernel_version() in managed_version.stdout
    # Upgrade in place: the inactive slot becomes active, commands still run,
    # and the pre-Custodian launcher backup must not be overwritten.
    _checked([
        sys.executable, str(installer), "--package", str(wheels[0]),
        "--runtime-root", str(managed), "--bin-dir", str(commands),
    ], env=env, timeout=300)
    managed_version = _checked([str(managed_custodian), "--version"], env=env, timeout=30)
    assert _kernel_version() in managed_version.stdout
    _checked([
        sys.executable, str(installer), "--runtime-root", str(managed),
        "--bin-dir", str(commands), "--uninstall",
    ], env=env, timeout=30)
    assert any(p.name.startswith("managed.removed") for p in managed.parent.iterdir()), (
        "uninstall must quarantine the runtime root (unique name: managed.removed-<pid>)"
    )
    # Compare raw bytes: read_text() default newline handling would translate
    # the Windows CRLF launcher to LF on read and the assert could never pass
    # on Windows even when the backup is byte-identical. (open() with
    # newline="" is used because Path.read_text() does not accept newline=.)
    with original_launcher.open(encoding="utf-8", newline="") as fh:
        launcher_now = fh.read()
    assert launcher_now == original_text
