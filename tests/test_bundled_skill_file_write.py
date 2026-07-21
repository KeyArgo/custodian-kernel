"""Tests for the file-write bundled skill's path-allowlist boundary check.

The old check was `realpath(path).startswith(realpath(ALLOWED))` with no
directory-separator boundary -- a sibling directory sharing ALLOWED as a
string prefix (e.g. ALLOWED=/tmp/allowed, target=/tmp/allowed-evil) passed
the check even though it isn't actually under the allowed directory.

No test coverage existed for this script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "bundled_skills" / "files" / "file-write" / "scripts" / "execute.py"
)


def _run(path: str, content: str, allowed_dir: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--path", path, "--content", content],
        capture_output=True, text=True, timeout=10,
        env={"CUSTODIAN_ALLOWED_WRITE_DIR": allowed_dir},
    )
    return json.loads(result.stdout)


def test_rejects_sibling_directory_sharing_a_string_prefix(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sibling = tmp_path / "allowed-evil"
    sibling.mkdir()
    target = sibling / "pwned.txt"

    out = _run(str(target), "data", str(allowed))
    assert out["ok"] is False
    assert "Path must be under" in out["error"]
    assert not target.exists()


def test_allows_a_path_actually_under_the_allowed_directory(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "sub" / "file.txt"
    target.parent.mkdir()

    out = _run(str(target), "hello", str(allowed))
    assert out["ok"] is True
    assert target.read_text() == "hello"


def test_allows_writing_the_allowed_directory_itself_as_a_file_sibling(tmp_path):
    # Regression guard: the exact-match branch (real == allowed_real) matters
    # for a file directly named the same as the allowed dir's parent case,
    # but writing *inside* the allowed dir (the common case) must still work.
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "file.txt"

    out = _run(str(target), "hi", str(allowed))
    assert out["ok"] is True
