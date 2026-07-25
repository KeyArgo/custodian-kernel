"""Builds the exact public kernel wheel, installs it into an isolated venv
with nothing
else on sys.path, and runs every registered CLI (sub)command's --help.

This is the test that would have caught the 0.4.0 incident: custodian/
cli/main.py imported cmd_console/cmd_codex_guard at module level, and both
imported from custodian.codex_guard.* at module level too. The actual
wheel uploaded to PyPI for 0.4.0 didn't include the codex_guard/
claude_guard/opencode_guard subpackages, so *every* CLI invocation --
including `custodian --version` -- crashed with ModuleNotFoundError. That
went undetected because every prior check either ran from inside the repo
checkout (where custodian.codex_guard resolves from the local tree
regardless of what the wheel actually contains) or hand-picked a fixed
list of commands to smoke-test rather than walking the real, live
argparse tree -- so a newly added subcommand with the same class of bug
would have slipped through unnoticed too.

Runs from a real subprocess with cwd outside the repo and PYTHONPATH
cleared, so accidentally resolving the package from the checkout (the
exact trap that hid this bug) is structurally impossible here.

Needs network (fresh venv has to fetch pyyaml/requests/cryptography/
tzdata) -- marked `network` like the rest of the network-dependent suite,
excluded by default locally, must run in CI.
"""
from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _iter_subcommand_paths() -> list[list[str]]:
    """Every leaf (sub)command path in the real argparse tree, e.g.
    ['codex-guard', 'receipts'] or ['tools', 'list']. Built by walking the
    actual parser custodian ships -- not a hand-maintained list -- so a
    newly added subcommand is covered automatically, with no one having to
    remember to update a fixture here."""
    # custodian-kernel is expected to be installed editable in the venv
    # running these tests (pointing at this exact checkout), so this
    # imports the real, current parser tree with no sys.path surgery.
    from custodian.cli.main import build_parser

    paths: list[list[str]] = []

    def walk(parser, prefix: list[str]) -> None:
        found_sub = False
        for action in parser._subparsers._group_actions if parser._subparsers else []:
            for name, subparser in action.choices.items():
                found_sub = True
                walk(subparser, prefix + [name])
        if not found_sub and prefix:
            paths.append(prefix)

    walk(build_parser(), [])
    return paths


@pytest.fixture(scope="module")
def clean_installed_cli(tmp_path_factory) -> Path:
    """Build the filtered release tree and pip install *only* its wheel.
    Returns the venv's bin/ dir. Session-scoped-ish (module here) since
    building + installing is the slow part and every test in this file
    shares the same clean install."""
    work = tmp_path_factory.mktemp("clean-wheel-install")
    release_tree = work / "release-tree"
    dist_dir = work / "dist"

    tree_result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/build-kernel-release-tree.py"),
            str(release_tree),
        ],
        capture_output=True, text=True, timeout=60,
    )
    assert tree_result.returncode == 0, (
        "release-tree build failed:\n"
        f"STDOUT:\n{tree_result.stdout}\nSTDERR:\n{tree_result.stderr}"
    )
    build_result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "-o", str(dist_dir), str(release_tree)],
        capture_output=True, text=True, timeout=300,
    )
    assert build_result.returncode == 0, (
        f"wheel build failed:\nSTDOUT:\n{build_result.stdout}\nSTDERR:\n{build_result.stderr}"
    )

    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found {wheels}"
    wheel = wheels[0]

    venv_dir = work / "venv"
    venv.create(venv_dir, with_pip=True)
    bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
    pip = bin_dir / ("pip.exe" if sys.platform == "win32" else "pip")

    install_result = subprocess.run(
        [str(pip), "install", "--quiet", str(wheel)],
        capture_output=True, text=True, timeout=300,
    )
    assert install_result.returncode == 0, (
        f"clean install of the built wheel failed:\n"
        f"STDOUT:\n{install_result.stdout}\nSTDERR:\n{install_result.stderr}"
    )

    return bin_dir


def _run_clean(bin_dir: Path, args: list[str]) -> subprocess.CompletedProcess:
    import os

    custodian = bin_dir / ("custodian.exe" if sys.platform == "win32" else "custodian")
    # cwd deliberately NOT the repo, and PYTHONPATH removed: this is the one
    # setup where a subpackage missing from the wheel actually shows up as
    # missing, instead of silently resolving from the local checkout. PATH
    # points only at the clean venv so the right interpreter/script runs;
    # everything else (HOME, LANG, ...) is inherited so the process starts
    # up normally rather than failing on unrelated missing env state.
    env = dict(os.environ)
    env["PATH"] = str(bin_dir)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [str(custodian), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(bin_dir.parent.parent),
        env=env,
    )


@pytest.mark.network
def test_version_works_from_clean_install(clean_installed_cli):
    result = _run_clean(clean_installed_cli, ["--version"])
    assert result.returncode == 0, (
        f"`custodian --version` failed from a clean wheel install "
        f"(exit {result.returncode}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


@pytest.mark.network
def test_top_level_help_works_from_clean_install(clean_installed_cli):
    result = _run_clean(clean_installed_cli, ["--help"])
    assert result.returncode == 0, (
        f"`custodian --help` failed from a clean wheel install:\n{result.stderr}"
    )


@pytest.mark.network
def test_console_status_works_from_clean_install(clean_installed_cli):
    result = _run_clean(clean_installed_cli, ["console", "--once"])
    assert result.returncode == 0, (
        f"`custodian console --once` failed from a clean wheel install:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


@pytest.mark.network
@pytest.mark.parametrize("path", _iter_subcommand_paths(), ids=lambda p: " ".join(p))
def test_every_subcommand_help_works_from_clean_install(clean_installed_cli, path):
    """`custodian <subcommand...> --help` must never crash from a real,
    clean install -- regardless of whether the subcommand's own runtime
    dependencies (a secrets file, network, credentials) are present.
    argparse resolves and prints help before any of that is touched, so a
    module-level import in the subcommand's own file is the only thing
    that can make this fail."""
    result = _run_clean(clean_installed_cli, [*path, "--help"])
    assert result.returncode == 0, (
        f"`custodian {' '.join(path)} --help` failed from a clean wheel "
        f"install (exit {result.returncode}):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
