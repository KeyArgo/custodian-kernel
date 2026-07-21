"""Tests for file-read/file-list directory-allowlist enforcement.

Both SKILL.md files already claimed "read from/list an allowed path", but
neither execute.py enforced any boundary at all -- any absolute path
(/etc/passwd, ~/.ssh/id_rsa, ~/.custodian/kv.db) was readable under an
autonomous, no-approval L0 band. Fixed with the same realpath + separator
boundary check already used by file-write.

No test coverage existed for either script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FILES_SKILLS = Path(__file__).resolve().parent.parent / "custodian" / "bundled_skills" / "files"


def _run(tool: str, args: list, allowed_dir: str) -> dict:
    script = FILES_SKILLS / tool / "scripts" / "execute.py"
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=10,
        env={"CUSTODIAN_ALLOWED_READ_DIR": allowed_dir},
    )
    return json.loads(result.stdout)


def test_file_read_blocks_a_path_outside_the_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("top secret")

    out = _run("file-read", ["--path", str(outside)], str(allowed))
    assert out["ok"] is False
    assert "Path must be under" in out["error"]


def test_file_read_blocks_sibling_dir_sharing_a_string_prefix(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sibling = tmp_path / "allowed-evil"
    sibling.mkdir()
    secret = sibling / "secret.txt"
    secret.write_text("top secret")

    out = _run("file-read", ["--path", str(secret)], str(allowed))
    assert out["ok"] is False
    assert "Path must be under" in out["error"]


def test_file_read_allows_a_path_actually_inside_the_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "notes.txt"
    target.write_text("hello world")

    out = _run("file-read", ["--path", str(target)], str(allowed))
    assert out["ok"] is True
    assert "hello world" in out["content"]


def test_file_list_blocks_a_path_outside_the_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "f.txt").write_text("x")

    out = _run("file-list", ["--path", str(outside)], str(allowed))
    assert out["ok"] is False
    assert "Path must be under" in out["error"]


def test_file_list_blocks_pattern_that_traverses_outside_allowed_dir(tmp_path):
    """--path itself may pass the check, but a pattern like "../../etc/*"
    still lets glob() resolve outside the allowed root -- each match must
    be checked too, not just the starting --path."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "secret_dir"
    outside.mkdir()
    (outside / "leak.txt").write_text("leak")

    out = _run("file-list", ["--path", str(allowed), "--pattern", "../secret_dir/*"], str(allowed))
    assert out["ok"] is True
    assert out["files"] == [], "traversal escaped the allowed root via the pattern"


def test_file_list_allows_a_path_actually_inside_the_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "a.txt").write_text("x")
    (allowed / "b.txt").write_text("y")

    out = _run("file-list", ["--path", str(allowed), "--pattern", "*.txt"], str(allowed))
    assert out["ok"] is True
    assert out["count"] == 2
