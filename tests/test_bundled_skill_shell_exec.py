"""Tests for the shell-exec bundled skill's command allowlist.

`python3` sat in the command allowlist at band L2 ("autonomous, routine")
with no argument restriction -- unlike git/curl/find, there's no safe
restricted subset of "run arbitrary code" reachable by denying a few flags,
so it's now removed entirely.

(A --workdir restriction was considered and reverted: the existing test
suite's own fixtures rely on --workdir pointing at an arbitrary directory,
e.g. the actual project repo for `git log`/`git status` -- git's `-C` flag
is already blocked by the subcommand allowlist, so --workdir is the *only*
legitimate way to point git at a specific repo. Every allowlisted binary
here already accepts arbitrary absolute-path arguments (cat/ls/grep/find/...)
with no directory restriction, so restricting --workdir specifically would
not close a distinct capability, only break intended, already-tested usage.)

No test coverage existed for this script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "bundled_skills" / "files" / "shell-exec" / "scripts" / "execute.py"
)


def _run(cmd: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--cmd", cmd],
        capture_output=True, text=True, timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )
    return json.loads(result.stdout)


def test_python3_is_no_longer_in_the_allowlist():
    out = _run("python3 -c 'import os; print(os.environ)'")
    assert out["ok"] is False
    assert "not in allowlist" in out["error"]
    assert "python3" in out["error"]


def test_still_allows_a_genuinely_allowlisted_command():
    out = _run("echo hello")
    assert out["ok"] is True
    assert out["stdout"].strip() == "hello"
