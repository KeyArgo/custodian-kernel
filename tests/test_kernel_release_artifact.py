"""Tests for the filtered public kernel artifact, not the larger monorepo."""
from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/build-kernel-release-tree.py"
KERNEL_PYPROJECT = ROOT / "packaging/kernel/pyproject.toml"


def _kernel_version() -> str:
    import re
    m = re.search(r'^version\s*=\s*"([^"]+)"', KERNEL_PYPROJECT.read_text(), re.MULTILINE)
    if m:
        return m.group(1)
    return "0.4.1"


def _tree(tmp_path: Path) -> Path:
    tree = tmp_path / "tree"
    subprocess.run([sys.executable, str(BUILDER), str(tree)], check=True)
    return tree


def test_release_tree_has_kernel_metadata_and_no_integrations(tmp_path):
    ver = _kernel_version()
    tree = _tree(tmp_path)
    metadata = (tree / "pyproject.toml").read_text()
    assert f'version = "{ver}"' in metadata
    assert "KeyArgo/custodian-kernel" in metadata
    # One-install-everything contract (0.5.0 fold): the public harness guards
    # ship in the kernel wheel; only the private in-progress opencode guard
    # (no public mirror, other lane's WIP) stays out.
    for package in ("codex_guard", "claude_guard", "hermes_guard"):
        assert (tree / "custodian" / package).is_dir(), f"{package} must ship"
    assert not (tree / "custodian" / "opencode_guard").exists()
    assert (tree / "custodian/policy/presets/default.yaml").is_file()
    assert (tree / "install-custodian.py").is_file()
    assert (tree / "CHANGELOG.md").is_file()
    assert (tree / "SECURITY.md").is_file()
    assert (tree / "CONTRIBUTING.md").is_file()
    assert (tree / "CODE_OF_CONDUCT.md").is_file()
    manifest = (tree / "MANIFEST.in").read_text()
    assert "include install-custodian.py" in manifest
    readme = (tree / "README.md").read_text()
    assert "PEP 668" in readme
    assert "install-custodian.py" in readme
    mirror = (ROOT / "scripts/publish-mirror.sh").read_text()
    assert "scripts/install-custodian.py:install-custodian.py" in mirror
    assert "packaging/kernel/MANIFEST.in:MANIFEST.in" in mirror
    assert "docs/SECURITY.md:SECURITY.md" in mirror


def test_release_tree_cli_imports_without_integrations(tmp_path):
    tree = _tree(tmp_path)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tree)
    code = """
import importlib.abc
import sys
class BlockIntegrations(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("custodian.codex_guard", "custodian.claude_guard",
                                "custodian.opencode_guard")):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=fullname)
        return None
sys.meta_path.insert(0, BlockIntegrations())
from custodian.cli.main import main
assert main(["--version"]) == 0
assert main(["console", "--once", "--state-dir", STATE]) == 0
assert main(["codex-guard", "receipts", "--state-dir", STATE]) == 2
"""
    result = subprocess.run(
        [sys.executable, "-c", f"STATE={str(tmp_path / 'state')!r}\n{code}"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.network
def test_built_release_wheel_manifest(tmp_path):
    ver = _kernel_version()
    tree = _tree(tmp_path)
    dist = tmp_path / "dist"
    result = subprocess.run(
        [
            sys.executable, "-m", "build", "--wheel",
            "--outdir", str(dist), str(tree),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheel = next(dist.glob("*.whl"))
    assert ver in wheel.name
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        entry_points = archive.read(
            next(name for name in names if name.endswith("entry_points.txt"))
        ).decode()
    assert "custodian/policy/presets/default.yaml" in names
    assert not any("/codex_guard/" in name for name in names)
    assert not any("/claude_guard/" in name for name in names)
    assert not any("/opencode_guard/" in name for name in names)
    assert "custodian-codex" not in entry_points


@pytest.mark.network
def test_built_release_sdist_includes_lifecycle_and_oss_docs(tmp_path):
    ver = _kernel_version()
    tree = _tree(tmp_path)
    dist = tmp_path / "dist"
    result = subprocess.run(
        [
            sys.executable, "-m", "build", "--sdist",
            "--outdir", str(dist), str(tree),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    sdist_path = next(dist.glob("*.tar.gz"))
    assert ver in sdist_path.name
    listing = subprocess.run(
        ["tar", "-tzf", str(sdist_path)],
        capture_output=True, text=True, check=True,
    ).stdout
    for filename in (
        "install-custodian.py",
        "CHANGELOG.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
    ):
        assert any(line.endswith(f"/{filename}") for line in listing.splitlines())
