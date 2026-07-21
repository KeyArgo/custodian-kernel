"""Tests for base64-encode/hash-sha256's --file directory-allowlist.

Both are simple string-transform utilities declared L0 ("read-only, no
real-world effects"), but --file let either read (and, for base64-encode,
directly return/exfiltrate) any file on disk with zero path restriction.
Fixed with the same realpath + separator boundary check used by
file-read/file-write.

No test coverage existed for either script's --file argument before this
fix.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

UTIL_SKILLS = Path(__file__).resolve().parent.parent / "custodian" / "bundled_skills" / "utilities"


def _run(tool: str, args: list, allowed_dir: str) -> dict:
    script = UTIL_SKILLS / tool / "scripts" / "execute.py"
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=10,
        env={"CUSTODIAN_ALLOWED_READ_DIR": allowed_dir},
    )
    return json.loads(result.stdout)


def test_base64_encode_blocks_file_outside_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("super secret content")

    out = _run("base64-encode", ["--file", str(secret)], str(allowed))
    assert out["ok"] is False
    assert "--file must be under" in out["error"]


def test_base64_encode_allows_file_inside_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "data.txt"
    target.write_text("hello")

    out = _run("base64-encode", ["--file", str(target)], str(allowed))
    assert out["ok"] is True
    assert base64.b64decode(out["encoded"]) == b"hello"


def test_base64_encode_still_encodes_plain_input_with_no_file(tmp_path):
    out = _run("base64-encode", ["--input", "hi there"], str(tmp_path))
    assert out["ok"] is True
    assert base64.b64decode(out["encoded"]) == b"hi there"


def test_hash_sha256_blocks_file_outside_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("super secret content")

    out = _run("hash-sha256", ["--file", str(secret)], str(allowed))
    assert out["ok"] is False
    assert "--file must be under" in out["error"]


def test_hash_sha256_allows_file_inside_allowed_dir(tmp_path):
    import hashlib
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "data.txt"
    target.write_bytes(b"hello")

    out = _run("hash-sha256", ["--file", str(target)], str(allowed))
    assert out["ok"] is True
    assert out["hash"] == hashlib.sha256(b"hello").hexdigest()
