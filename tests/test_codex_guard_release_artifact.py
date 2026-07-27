"""Tests for the filtered, installable Codex Guard public artifact."""
from __future__ import annotations

import os
import json
import subprocess
import sys
import venv
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/build-codex-guard-release-tree.py"
KERNEL_BUILDER = ROOT / "scripts/build-kernel-release-tree.py"


def _checked(
    command: list[str], **kwargs
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )
    assert result.returncode == 0, (
        f"command failed ({result.returncode}): {' '.join(command)}\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return result


def _tree(tmp_path: Path) -> Path:
    tree = tmp_path / "tree"
    subprocess.run([sys.executable, str(BUILDER), str(tree)], check=True)
    return tree


def test_release_tree_contains_self_contained_plugin_marketplace(tmp_path):
    tree = _tree(tmp_path)
    bundle = tree / "custodian/codex_guard/bundled_plugin"
    assert (bundle / ".agents/plugins/marketplace.json").is_file()
    assert (
        bundle
        / "plugins/custodian-codex-guard/.codex-plugin/plugin.json"
    ).is_file()
    assert (
        bundle
        / "plugins/custodian-codex-guard/skills/govern-codex/SKILL.md"
    ).is_file()


def test_release_metadata_declares_commands_and_supported_platforms(tmp_path):
    tree = _tree(tmp_path)
    metadata = (tree / "pyproject.toml").read_text(encoding="utf-8")
    for command in (
        "custodian-codex",
        "custodian-codex-guard-mcp",
        "custodian-codex-guard-hook",
    ):
        assert command in metadata
    assert "Operating System :: POSIX :: Linux" in metadata
    assert "Operating System :: MacOS" in metadata
    assert "Operating System :: OS Independent" not in metadata


@pytest.mark.network
def test_exact_wheels_run_documented_setup_from_any_directory_and_preserve_data(
    tmp_path,
):
    kernel_tree = tmp_path / "kernel-tree"
    guard_tree = tmp_path / "guard-tree"
    dist = tmp_path / "dist"
    dist.mkdir()
    _checked([sys.executable, str(KERNEL_BUILDER), str(kernel_tree)], timeout=60)
    _checked([sys.executable, str(BUILDER), str(guard_tree)], timeout=60)
    for tree in (kernel_tree, guard_tree):
        _checked(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--outdir",
                str(dist),
                str(tree),
            ],
            timeout=300,
        )

    kernel_wheel = next(dist.glob("custodian_kernel-0.4.1-*.whl"))
    guard_wheel = next(dist.glob("custodian_codex_guard-0.1.2-*.whl"))
    environment = tmp_path / "runtime"
    venv.create(environment, with_pip=True)
    bin_dir = environment / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    pip = bin_dir / ("pip.exe" if os.name == "nt" else "pip")
    _checked(
        [str(pip), "install", str(kernel_wheel), str(guard_wheel)],
        timeout=300,
    )
    _checked([str(pip), "check"], timeout=30)

    home = tmp_path / "home"
    codex_home = home / ".codex"
    state = home / ".custodian"
    unrelated = tmp_path / "unrelated-working-directory"
    unrelated.mkdir()
    markers = [
        state / "vaults/KEEP",
        state / "ledger/KEEP",
        home / ".paladin/KEEP",
        home / ".talaria/KEEP",
    ]
    for marker in markers:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(b"preserve\x00data")

    # setup only needs the stable Codex CLI command contract. This fixture
    # keeps the regression offline from Codex services and isolated from the
    # operator's real profile.
    codex = bin_dir / ("codex.cmd" if os.name == "nt" else "codex")
    if os.name == "nt":
        codex.write_text("@echo off\r\nexit /b 0\r\n", encoding="utf-8")
    else:
        codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        codex.chmod(0o755)

    env = dict(
        os.environ,
        HOME=str(home),
        CODEX_HOME=str(codex_home),
        CUSTODIAN_CODEX_GUARD_STATE_DIR=str(state),
        PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    )
    env.pop("PYTHONPATH", None)
    _checked(["custodian-codex", "setup"], cwd=unrelated, env=env, timeout=60)
    doctor = _checked(
        ["custodian-codex", "doctor"],
        cwd=unrelated,
        env=env,
        timeout=60,
    )
    assert "MCP server" in doctor.stdout
    assert "enforcement hook" in doctor.stdout
    handshake = _checked(
        ["custodian-codex-guard-mcp"],
        cwd=unrelated,
        env=env,
        input=(
            '{"jsonrpc":"2.0","id":1,"method":"initialize",'
            '"params":{"protocolVersion":"2025-06-18"}}\n'
        ),
        timeout=30,
    )
    response = json.loads(handshake.stdout)
    assert response["result"]["serverInfo"] == {
        "name": "custodian-codex-guard",
        "version": "0.1.2",
    }
    _checked(
        ["custodian-codex", "hook-uninstall"],
        cwd=unrelated,
        env=env,
        timeout=30,
    )
    _checked(
        [str(pip), "uninstall", "--yes", "custodian-codex-guard"],
        cwd=unrelated,
        env=env,
        timeout=60,
    )
    for marker in markers:
        assert marker.read_bytes() == b"preserve\x00data"
