"""Tests for scripts/dev-install.py.

These tests are unit-level and fully isolated:
- No real pip installs are executed (args are verified structurally).
- No shell, git, network, credentials, or file modifications.
- Dry-run and --print-pip-cmd paths are exercised.
- Argument parsing is validated for every mode.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev-install.py"


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


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_flag(flag: str):
    result = run([flag])
    assert result.returncode == 0
    assert "usage:" in result.stdout.lower() or "usage:" in result.stderr.lower()


def test_unknown_mode_is_rejected():
    result = run(["--mode", "nonsense"])
    assert result.returncode != 0
    assert "nonsense" in (result.stdout + result.stderr)


def test_default_mode_is_editable():
    result = run(["--print-pip-cmd", "--mode", "editable"])
    assert result.returncode == 0
    result_default = run(["--print-pip-cmd"])
    assert result.stdout == result_default.stdout


@pytest.mark.parametrize("mode", ["editable", "fresh", "upgrade", "repair"])
def test_print_pip_cmd_for_each_mode(mode: str):
    result = run(["--print-pip-cmd", "--mode", mode])
    assert result.returncode == 0, f"failed for mode={mode}: {result.stderr}"
    cmd = result.stdout.strip()
    assert cmd.startswith(sys.executable)
    assert "pip" in cmd
    assert "install" in cmd


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

def test_dry_run_does_not_error():
    """Dry-run should always succeed by printing what would happen."""
    for mode in ("editable", "fresh", "upgrade", "repair"):
        result = run(["--mode", mode, "--dry-run"])
        assert result.returncode == 0, f"dry-run failed for mode={mode}: {result.stderr}"
        assert "[dry-run]" in result.stdout, f"missing [dry-run] marker for mode={mode}"


def test_dry_run_fresh_mentions_venv():
    result = run(["--mode", "fresh", "--dry-run"])
    assert result.returncode == 0
    assert "[dry-run]" in result.stdout
    assert "venv" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Output diagnostics
# ---------------------------------------------------------------------------

def test_verbose_flag_accepted():
    """--verbose should be accepted (no real pip run in unit test)."""
    result = run(["--mode", "editable", "--dry-run", "--verbose"])
    assert result.returncode == 0


def test_print_pip_cmd_output_format():
    """--print-pip-cmd must output a valid-looking command."""
    result = run(["--print-pip-cmd", "--mode", "repair"])
    assert result.returncode == 0
    line = result.stdout.strip()
    assert "pip" in line
    assert "--force-reinstall" in line
    assert "--no-cache-dir" in line


# ---------------------------------------------------------------------------
# Argument combinations
# ---------------------------------------------------------------------------

def test_dry_run_and_print_cmd_are_mutually_compatible():
    """Both flags can be passed; --print-pip-cmd takes precedence for output."""
    result = run(["--dry-run", "--print-pip-cmd"])
    assert result.returncode == 0


def test_verbose_dry_run_prints_dry_run_marker():
    result = run(["--verbose", "--dry-run"])
    assert "[dry-run]" in result.stdout


# ---------------------------------------------------------------------------
# Script entry convention
# ---------------------------------------------------------------------------

def test_script_has_main_function():
    """dev-install.py must expose a main() and use raise SystemExit."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def main()" in source
    assert "raise SystemExit(main())" in source or "sys.exit(main())" in source


def test_script_uses_path_resolution():
    """Script must derive PROJECT_ROOT from __file__ (no cwd reliance)."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "__file__" in source
    assert "parents[1]" in source or "parent" in source


# ---------------------------------------------------------------------------
# Mode-specific pip-arg construction (indirect via --print-pip-cmd)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("mode", "expected_substrings"),
    [
        ("editable", ["-e "]),
        ("fresh", ["-e ", "--ignore-installed"]),
        ("upgrade", ["-e ", "--upgrade"]),
        ("repair", ["-e ", "--force-reinstall", "--no-cache-dir"]),
    ],
)
def test_mode_pip_args(mode: str, expected_substrings: list[str]):
    result = run(["--print-pip-cmd", "--mode", mode])
    assert result.returncode == 0
    for sub in expected_substrings:
        assert sub in result.stdout, f"mode={mode} missing '{sub}' in {result.stdout}"
