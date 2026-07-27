"""Release qualification must remain exhaustive and preparation-only."""
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "prepare-release.yml"
)


def _source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_release_qualification_covers_every_supported_os_and_python():
    source = _source()
    assert source.count("os: [ubuntu-latest, macos-latest]") == 2
    assert "os: [ubuntu-latest, windows-latest, macos-latest]" not in source
    assert source.count('python-version: ["3.11", "3.12", "3.13"]') == 2
    assert "needs: source-qualification" in source
    assert "needs: prepare" in source


def test_exact_uploaded_artifact_is_installed_without_rebuild():
    source = _source()
    artifact_section = source.split("artifact-qualification:", 1)[1]
    assert "actions/download-artifact@" in artifact_section
    assert '"$PYTHON" -m pip install "$COMPONENT_WHEEL"' in artifact_section
    assert "python -m build" not in artifact_section
    assert "pip check" in artifact_section


def test_kernel_release_smoke_covers_original_install_regression():
    source = _source()
    for command in (
        '"$BIN/custodian" --version',
        '"$BIN/custodian" console --once',
        '"$BIN/paladin" --help',
    ):
        assert command in source


def test_codex_guard_release_smoke_requires_real_mcp_handshake_and_version():
    source = _source()
    assert "custodian-codex-guard-mcp > mcp-response.json" in source
    assert '"method":"initialize"' in source
    assert "serverInfo" in source
    assert "inputs.version" in source


def test_codex_guard_release_runs_the_documented_bare_commands():
    source = _source()
    assert "export PATH=" in source
    assert "custodian-codex setup" in source
    assert "custodian-codex doctor" in source
    assert '"$BIN/custodian-codex" setup' not in source
    assert "CODEX_HOME:" in source
    assert "CUSTODIAN_CODEX_GUARD_STATE_DIR:" in source


def test_codex_guard_rebuilds_exact_kernel_dependency_from_same_checkout():
    source = _source()
    assert "kernel_version:" in source
    assert "Build exact kernel dependency for Codex Guard" in source
    assert "kernel-${{ inputs.kernel_version }}/artifacts/*.whl" in source
    assert "-path '*kernel-${{ inputs.kernel_version }}*'" in source


def test_workflow_has_read_only_github_permissions_and_no_publish_step():
    source = _source()
    assert "permissions:\n  contents: read" in source
    forbidden = (
        "pypa/gh-action-pypi-publish",
        "twine upload",
        "gh release create",
        "git tag ",
        "git push ",
    )
    for phrase in forbidden:
        assert phrase not in source
