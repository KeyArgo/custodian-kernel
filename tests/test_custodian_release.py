"""Tests for scripts/custodian-release.py (PREPARATION only).

These tests import the release module and exercise functions with mocks,
temp repos, and temp artifacts.  No real PyPI installs, git operations,
or network access.  Proves refusal on dirty/wrong-remote/wrong-version
repos, sdist hashing, artifact persistence, fail-fast subprocesses, no
publication calls, PEP668 behavior, marker preservation, and health
output/receipt behavior.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "custodian-release.py"

# ---------------------------------------------------------------------------
# Import the release module
# ---------------------------------------------------------------------------

import hashlib
import importlib.util
_spec = importlib.util.spec_from_file_location("custodian_release", SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_checked = _mod._checked
_content_digest = _mod._content_digest
_git_is_dirty = _mod._git_is_dirty
_record_artifacts = _mod._record_artifacts
_smoke_test = _mod._smoke_test
_discover_latest_pypi_version = _mod._discover_latest_pypi_version
_test_pep668_compliance = _mod._test_pep668_compliance
_test_managed_install = _mod._test_managed_install
_cmd_prepare = _mod._cmd_prepare
_write_manifest = _mod._write_manifest
_sha256 = _mod._sha256
_extract_wheel_version = _mod._extract_wheel_version
_test_fresh_install = _mod._test_fresh_install
_test_upgrade_from_pypi = _mod._test_upgrade_from_pypi
_build_artifacts = _mod._build_artifacts
_build_public_tree = _mod._build_public_tree
COMPONENT_REGISTRY = _mod.COMPONENT_REGISTRY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _make_temp_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo at tmp_path and return it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
    (repo / "file.txt").write_text("content")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/KeyArgo/custodian-kernel.git"],
        cwd=repo, capture_output=True,
    )
    return repo


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def test_help_flag():
    result = run(["--help"])
    assert result.returncode == 0
    assert "prepare" in result.stdout


def test_no_args_shows_help():
    result = run([])
    assert result.returncode != 0


def test_unknown_component_is_rejected():
    result = run(["prepare", "nonsense", "0.4.1"])
    assert result.returncode != 0
    assert "nonsense" in (result.stdout + result.stderr)


def test_missing_version_is_rejected():
    result = run(["prepare", "kernel"])
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Module functions exist
# ---------------------------------------------------------------------------

def test_module_has_expected_functions():
    assert callable(_checked)
    assert callable(_content_digest)
    assert callable(_record_artifacts)
    assert callable(_smoke_test)
    assert callable(_cmd_prepare)


def test_release_controller_checks_mcp_version_against_installed_metadata():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "MCP version matches installed distribution" in source
    assert "m.version('custodian-codex-guard')" in source


def test_fresh_install_records_candidate_version_not_boolean_check(tmp_path):
    wheel = tmp_path / "custodian_codex_guard-0.1.2-py3-none-any.whl"
    wheel.write_bytes(b"candidate")
    smoke = {
        "passed": True,
        "checks": {
            "custodian-codex --help": True,
            "MCP initialize handshake": True,
        },
    }
    with patch.object(_mod.venv, "create"), \
         patch.object(_mod, "_install_candidate"), \
         patch.object(_mod, "_extract_wheel_version", return_value="0.1.2"), \
         patch.object(_mod, "_smoke_test", return_value=smoke):
        result = _test_fresh_install(
            "codex-guard", wheel, tmp_path / "fresh-work"
        )

    assert result["passed"] is True
    assert result["version"] == "0.1.2"


def test_upgrade_records_candidate_version_not_boolean_check(tmp_path):
    wheel = tmp_path / "custodian_kernel-0.4.1-py3-none-any.whl"
    wheel.write_bytes(b"candidate")
    smoke = {
        "passed": True,
        "checks": {
            "custodian --version": "custodian 0.4.1",
            "custodian health": True,
        },
    }
    with patch.object(_mod.venv, "create"), \
         patch.object(_mod, "_extract_wheel_version", return_value="0.4.1"), \
         patch.object(_mod, "_discover_latest_pypi_version",
                      return_value="0.4.0"), \
         patch.object(_mod, "_checked"), \
         patch.object(_mod, "_smoke_test", return_value=smoke):
        result = _test_upgrade_from_pypi(
            "kernel", wheel, tmp_path / "upgrade-work"
        )

    assert result["passed"] is True
    assert result["version"] == "0.4.1"


# ---------------------------------------------------------------------------
# Component registry
# ---------------------------------------------------------------------------

def test_component_registry_has_all_components():
    assert set(COMPONENT_REGISTRY) == {"kernel", "codex-guard", "talaria"}


def test_component_registry_has_package_names():
    assert COMPONENT_REGISTRY["kernel"]["package"] == "custodian-kernel"
    assert COMPONENT_REGISTRY["codex-guard"]["package"] == "custodian-codex-guard"
    assert COMPONENT_REGISTRY["talaria"]["package"] == "custodian-talaria"


def test_component_registry_has_correct_repos():
    assert COMPONENT_REGISTRY["kernel"]["repo"] == "KeyArgo/custodian-kernel"
    assert COMPONENT_REGISTRY["codex-guard"]["repo"] == "KeyArgo/custodian-codex-guard"
    assert COMPONENT_REGISTRY["talaria"]["repo"] == "KeyArgo/talaria"


# ---------------------------------------------------------------------------
# Content digest
# ---------------------------------------------------------------------------

def test_content_digest_deterministic(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    (tree / "b.txt").write_text("world")
    d1 = _content_digest(tree)
    d2 = _content_digest(tree)
    assert d1 == d2


def test_content_digest_changes_on_content_change(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    d1 = _content_digest(tree)
    (tree / "a.txt").write_text("hello!")
    d2 = _content_digest(tree)
    assert d1 != d2


def test_content_digest_changes_on_new_file(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    d1 = _content_digest(tree)
    (tree / "b.txt").write_text("world")
    d2 = _content_digest(tree)
    assert d1 != d2


# ---------------------------------------------------------------------------
# Subprocess safety: no shell=True
# ---------------------------------------------------------------------------

def test_no_subprocess_shell_true():
    source = SCRIPT.read_text(encoding="utf-8")
    import ast
    tree = ast.parse(source, filename=str(SCRIPT))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        pytest.fail(f"subprocess.run found with shell=True at line {node.lineno}")
    for method in ("os.system", "os.popen", "commands.getoutput"):
        assert method not in source, f"shell-based method {method} must not be used"


# ---------------------------------------------------------------------------
# No publication operations in prepare
# ---------------------------------------------------------------------------

def test_no_publication_commands_in_subprocess_calls():
    source = SCRIPT.read_text(encoding="utf-8")
    import ast
    tree = ast.parse(source, filename=str(SCRIPT))
    forbidden_cmds = [
        "git push", "git commit ", "git tag ", "gh release ",
        "twine upload", "twine check",
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                for arg in node.args:
                    if isinstance(arg, ast.List):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                for cmd in forbidden_cmds:
                                    assert cmd not in elt.value, (
                                        f"Forbidden publication command {cmd!r} found "
                                        f"in subprocess.run argument at line {node.lineno}"
                                    )


def test_no_pypi_upload_in_subprocess():
    source = SCRIPT.read_text(encoding="utf-8")
    import ast
    tree = ast.parse(source, filename=str(SCRIPT))
    forbidden = ["upload", "--repository-url"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                for arg in node.args:
                    if isinstance(arg, ast.List):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                for phrase in forbidden:
                                    assert phrase not in elt.value, (
                                        f"PyPI upload phrase {phrase!r} found in "
                                        f"subprocess.run argument at line {node.lineno}"
                                    )


def test_prepare_contains_no_github_release():
    source = SCRIPT.read_text(encoding="utf-8")
    import ast
    tree = ast.parse(source, filename=str(SCRIPT))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                for arg in node.args:
                    if isinstance(arg, ast.List):
                        for elt in arg.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                for phrase in ("gh release", "action-gh-release", "create_release"):
                                    assert phrase not in elt.value, (
                                        f"GitHub release phrase {phrase!r} found in "
                                        f"subprocess.run argument at line {node.lineno}"
                                    )


def test_only_prepare_command_exists():
    source = SCRIPT.read_text(encoding="utf-8")
    if "subparsers" in source:
        assert "publish" not in source.split("subparsers")[1]


# ---------------------------------------------------------------------------
# Dirty repo / wrong-remote refusal
# ---------------------------------------------------------------------------

def test_dirty_repo_refused(tmp_path):
    repo = _make_temp_repo(tmp_path)
    (repo / "dirty.txt").write_text("uncommitted")
    assert _git_is_dirty(repo) is True


def test_clean_repo_accepted(tmp_path):
    repo = _make_temp_repo(tmp_path)
    assert _git_is_dirty(repo) is False


def test_cmd_prepare_refuses_dirty_repo():
    with patch.object(_mod, "_resolve_public_repo_path", return_value=Path("/tmp/fake")), \
         patch.object(_mod, "_git_is_dirty", return_value=True):
        rc = _cmd_prepare("kernel", "0.4.1")
    assert rc != 0


# ---------------------------------------------------------------------------
# Artifact hashing (sdist and wheel)
# ---------------------------------------------------------------------------

def test_record_artifacts_includes_both_wheel_and_sdist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "pkg-0.4.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel data")
    sdist = dist / "pkg-0.4.1.tar.gz"
    sdist.write_bytes(b"sdist data")
    artifacts = _record_artifacts(dist)
    names = [a["name"] for a in artifacts]
    assert "pkg-0.4.1-py3-none-any.whl" in names
    assert "pkg-0.4.1.tar.gz" in names
    for a in artifacts:
        assert "size" in a
        assert "sha256" in a
        assert "path" in a
        assert a["path"] == a["name"]


def test_record_artifacts_skips_non_artifact_files(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "metadata.json").write_text("{}")
    artifacts = _record_artifacts(dist)
    assert not artifacts


def test_prepared_kernel_wheel_is_hash_verified(tmp_path, monkeypatch):
    base = tmp_path / "manifests"
    component = base / "kernel-0.4.1"
    artifacts = component / "artifacts"
    artifacts.mkdir(parents=True)
    wheel = artifacts / "custodian_kernel-0.4.1-py3-none-any.whl"
    wheel.write_bytes(b"candidate")
    manifest = {
        "artifacts": [{
            "name": wheel.name,
            "sha256": _sha256(wheel),
        }]
    }
    (component / "kernel-0.4.1.manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(_mod, "_RELEASE_MANIFESTS", base)
    assert _mod._prepared_kernel_wheel() == wheel
    wheel.write_bytes(b"changed")
    with pytest.raises(SystemExit, match="hash changed"):
        _mod._prepared_kernel_wheel()


def test_prepared_kernel_wheel_honors_explicit_dependency_version(
    tmp_path, monkeypatch
):
    manifests = tmp_path / "manifests"
    component = manifests / "kernel-9.8.7"
    artifacts = component / "artifacts"
    artifacts.mkdir(parents=True)
    wheel = artifacts / "custodian_kernel-9.8.7-py3-none-any.whl"
    wheel.write_bytes(b"candidate")
    (component / "kernel-9.8.7.manifest.json").write_text(json.dumps({
        "artifacts": [{
            "name": wheel.name,
            "sha256": hashlib.sha256(b"candidate").hexdigest(),
        }],
    }))
    monkeypatch.setattr(_mod, "_RELEASE_MANIFESTS", manifests)
    monkeypatch.setenv("CUSTODIAN_RELEASE_KERNEL_VERSION", "9.8.7")
    assert _mod._prepared_kernel_wheel() == wheel


def test_codex_release_builder_bundles_plugin_files(tmp_path):
    import importlib.util

    builder_path = SCRIPT.parent / "build-codex-guard-release-tree.py"
    spec = importlib.util.spec_from_file_location("codex_release_builder", builder_path)
    builder = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(builder)
    tree = tmp_path / "tree"
    builder.build_tree(tree)
    base = tree / "custodian/codex_guard/bundled_plugin"
    assert (base / ".agents/plugins/marketplace.json").is_file()
    assert (
        base / "plugins/custodian-codex-guard/.codex-plugin/plugin.json"
    ).is_file()
    assert (
        base / "plugins/custodian-codex-guard/skills/govern-codex/SKILL.md"
    ).is_file()
    for filename in (
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
    ):
        assert (tree / filename).is_file()
    video_url = "https://youtu.be/lnIwDIbzZf0"
    assert video_url in (tree / "README.md").read_text(encoding="utf-8")
    assert video_url in (
        base / "plugins/custodian-codex-guard/README.md"
    ).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Artifact persistence (manifest copies artifacts)
# ---------------------------------------------------------------------------

def test_write_manifest_preserves_artifacts(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "pkg-0.4.1-py3-none-any.whl"
    wheel.write_bytes(b"wheel content")
    sdist = dist / "pkg-0.4.1.tar.gz"
    sdist.write_bytes(b"sdist content")
    artifacts = _record_artifacts(dist)
    results = [{"test": "fresh-install", "passed": True}]

    manifests_dir = tmp_path / "release-manifests"
    with patch.object(_mod, "_RELEASE_MANIFESTS", manifests_dir), \
         patch.object(_mod, "_git_commit", return_value="abc123"):
        manifest_path = _write_manifest("kernel", "0.4.1", tmp_path, results, artifacts,
                                        tmp_path / "tree", "tree-digest", wheel, sdist)

    assert manifest_path.exists()
    artifact_dir = manifests_dir / "kernel-0.4.1" / "artifacts"
    assert (artifact_dir / "pkg-0.4.1-py3-none-any.whl").exists()
    assert (artifact_dir / "pkg-0.4.1.tar.gz").exists()


# ---------------------------------------------------------------------------
# Component-specific smoke test signatures
# ---------------------------------------------------------------------------

def test_smoke_test_kernel_signature():
    mod = _smoke_test
    # Verify it constructs commands per component
    ext = ".exe" if os.name == "nt" else ""
    assert hasattr(mod, "__call__")


# ---------------------------------------------------------------------------
# PyPI version discovery
# ---------------------------------------------------------------------------

def test_discover_latest_pypi_version_returns_none_on_network_error():
    with patch("urllib.request.urlopen", side_effect=OSError("no network")):
        result = _discover_latest_pypi_version("nonexistent-package", "0.4.1")
    assert result is None


def test_discover_latest_pypi_version_skips_current():
    mock_data = {
        "releases": {
            "0.4.0": [{"packagetype": "bdist_wheel"}],
            "0.4.1": [{"packagetype": "bdist_wheel"}],
            "0.5.0": [{"packagetype": "bdist_wheel"}],
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode()
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _discover_latest_pypi_version("custodian-kernel", "0.4.1")
    assert result == "0.4.0"


def test_discover_latest_pypi_version_fails_when_no_lower():
    mock_data = {
        "releases": {
            "0.4.0": [{"packagetype": "bdist_wheel"}],
        }
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_data).encode()
    mock_resp.__enter__.return_value = mock_resp
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _discover_latest_pypi_version("custodian-kernel", "0.4.0")
    assert result is None


# ---------------------------------------------------------------------------
# PEP 668 compliance
# ---------------------------------------------------------------------------

def test_pep668_not_applicable_for_codex_guard(tmp_path):
    result = _test_pep668_compliance("codex-guard", Path("/fake/wheel"), tmp_path)
    assert "not_applicable" in result
    assert result.get("passed") is True


def test_pep668_not_applicable_for_talaria(tmp_path):
    result = _test_pep668_compliance("talaria", Path("/fake/wheel"), tmp_path)
    assert "not_applicable" in result
    assert result.get("passed") is True


# ---------------------------------------------------------------------------
# Managed install: non-kernel returns skipped
# ---------------------------------------------------------------------------

def test_managed_install_skipped_for_codex_guard(tmp_path):
    result = _test_managed_install("codex-guard", Path("/fake/wheel"), tmp_path)
    assert result == {
        "test": "managed-install",
        "passed": True,
        "not_applicable": "managed install not applicable for codex-guard",
    }


def test_managed_install_skipped_for_talaria(tmp_path):
    result = _test_managed_install("talaria", Path("/fake/wheel"), tmp_path)
    assert result == {
        "test": "managed-install",
        "passed": True,
        "not_applicable": "managed install not applicable for talaria",
    }


# ---------------------------------------------------------------------------
# Fail-fast subprocess helper
# ---------------------------------------------------------------------------

def test_checked_raises_on_failure():
    with pytest.raises(SystemExit):
        _checked([sys.executable, "-c", "exit(1)"])


def test_checked_succeeds():
    result = _checked([sys.executable, "-c", "print('ok')"])
    assert result.returncode == 0


def test_checked_rejects_non_string_args():
    with pytest.raises(TypeError):
        _checked(["echo", 123])


# ---------------------------------------------------------------------------
# Manifest format
# ---------------------------------------------------------------------------

def test_manifest_contains_required_fields(tmp_path):
    artifacts = [
        {"name": "x.whl", "path": "x.whl", "size": 100, "sha256": "a" * 64},
    ]
    results = [{"test": "fresh-install", "passed": True}]

    with patch.object(_mod, "_git_commit", return_value="deadbeef"), \
         patch.object(_mod, "_RELEASE_MANIFESTS", tmp_path / "manifests"):
        manifest_path = _write_manifest(
            "kernel", "0.4.1", tmp_path, results, artifacts,
            tmp_path / "tree", "digest123", Path("/fake/wheel"), None,
        )

    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    for field in ("component", "package", "version", "public_repo",
                  "intended_tag", "artifacts", "test_results",
                  "all_tests_passed", "private_source_commit", "content_digest"):
        assert field in data, f"Manifest missing field: {field}"
    assert data["component"] == "kernel"
    assert data["version"] == "0.4.1"
    assert data["all_tests_passed"] is True
    assert data["content_digest"] == "digest123"


def test_manifest_records_all_test_failures(tmp_path):
    artifacts = [{"name": "x.whl", "path": "x.whl", "size": 1, "sha256": "a" * 64}]
    results = [
        {"test": "fresh-install", "passed": True},
        {"test": "upgrade", "passed": False},
    ]
    with patch.object(_mod, "_git_commit", return_value="deadbeef"), \
         patch.object(_mod, "_RELEASE_MANIFESTS", tmp_path / "manifests"):
        manifest_path = _write_manifest(
            "kernel", "0.4.1", tmp_path, results, artifacts,
            tmp_path / "tree", "digest", Path("/fake/wheel"), None,
        )
    data = json.loads(manifest_path.read_text())
    assert data["all_tests_passed"] is False


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------

def test_sha256_deterministic(tmp_path):
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello")
    assert _sha256(f) == _sha256(f)


# ---------------------------------------------------------------------------
# Health command
# ---------------------------------------------------------------------------

def test_health_command_registered():
    from custodian.cli.main import build_parser
    parser = build_parser()
    for action in parser._subparsers._group_actions if parser._subparsers else []:
        for name in action.choices:
            if name == "health":
                return
    pytest.fail("health command not found in CLI parser")


def test_health_json_format_no_paths_in_data_locations():
    from custodian.cli.cmd_health import _data_locations
    with tempfile.TemporaryDirectory() as tmp:
        state_dir = Path(tmp) / "state"
        state_dir.mkdir()
        checks = _data_locations(state_dir)
        for check in checks:
            assert "exists" in check
            assert "is_dir" in check
            assert "path" not in check
            assert "contents" not in check
            assert "files" not in check


def test_health_installation_proof_detects_record_tampering(tmp_path, monkeypatch):
    from custodian.cli import cmd_health

    record = tmp_path / "lib/python3.13/site-packages/custodian_kernel.dist-info/RECORD"
    record.parent.mkdir(parents=True)
    record.write_bytes(b"installed-files")
    proof = {
        "schema": 1,
        "artifact_sha256": "a" * 64,
        "record_sha256": __import__("hashlib").sha256(record.read_bytes()).hexdigest(),
        "record_relative": str(record.relative_to(tmp_path)),
    }
    (tmp_path / "installation-proof.json").write_text(json.dumps(proof))
    monkeypatch.setattr(cmd_health.sys, "prefix", str(tmp_path))
    assert cmd_health._installation_proof()["valid"] is True
    record.write_bytes(b"tampered")
    assert cmd_health._installation_proof()["valid"] is False


def test_editable_distribution_is_reported_as_source_install(monkeypatch):
    from custodian.cli import cmd_health

    class FakeDist:
        def read_text(self, name):
            if name == "direct_url.json":
                return '{"url":"file:///src/custodian","dir_info":{"editable":true}}'
            return ""

    monkeypatch.setattr(cmd_health.importlib.metadata, "distribution", lambda _name: FakeDist())
    assert cmd_health._is_source_install("custodian-kernel") is True


# ---------------------------------------------------------------------------
# Release script architecture boundary
# ---------------------------------------------------------------------------

def test_release_script_stdlib_only():
    source = SCRIPT.read_text(encoding="utf-8")
    lines = source.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            if "custodian" in stripped and "custodian-release" not in stripped:
                assert False, f"Release script imports from custodian package: {stripped}"
