"""Tests for s3-get's --output directory-allowlist enforcement.

Declared L0 (read-only, no real-world effects), but --output was passed
straight to boto3's download_file() with zero path validation --
S3-controlled bytes could overwrite any file the process can write
(~/.bashrc, a cron script, authorized_keys). Fixed with the same
realpath + separator boundary check used by file-write.

No test coverage existed for this script before this fix.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "bundled_skills" / "cloud" / "s3-get" / "scripts" / "execute.py"
)

_ENV = {
    "AWS_ACCESS_KEY_ID": "test-key",
    "AWS_SECRET_ACCESS_KEY": "test-secret",
}


def _run(args: list, allowed_dir: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=10,
        env={**_ENV, "CUSTODIAN_ALLOWED_WRITE_DIR": allowed_dir},
    )
    return json.loads(result.stdout)


def test_blocks_output_path_outside_allowed_dir(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = tmp_path / "bashrc_overwrite"

    out = _run(["--bucket", "b", "--key", "k", "--output", str(target)], str(allowed))
    assert out["ok"] is False
    assert "--output must be under" in out["error"]
    assert not target.exists()


def test_blocks_sibling_dir_sharing_a_string_prefix(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sibling = tmp_path / "allowed-evil"
    sibling.mkdir()
    target = sibling / "pwned.txt"

    out = _run(["--bucket", "b", "--key", "k", "--output", str(target)], str(allowed))
    assert out["ok"] is False
    assert "--output must be under" in out["error"]


def test_output_path_validation_happens_before_any_boto3_call(tmp_path):
    """The path check must reject before download_file() is ever reached
    -- prove this by using an obviously-invalid bucket/key (which would
    error at the AWS layer if reached) and confirming the error is still
    the path-boundary message, not a boto3/connection error."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = tmp_path / "outside.txt"

    out = _run(["--bucket", "", "--key", "", "--output", str(target)], str(allowed))
    assert out["ok"] is False
    assert "--output must be under" in out["error"]


def test_no_output_arg_skips_the_path_check_entirely():
    """When --output is omitted, the tool returns inline content instead
    of writing a file -- confirm the boundary check is scoped to the
    --output branch only by reading the source, since exercising the
    no-output path for real requires live AWS credentials/network."""
    src = SCRIPT.read_text()
    assert "if a.output:" in src
    check_pos = src.index("--output must be under")
    branch_pos = src.index("if a.output:")
    download_pos = src.index("s3.download_file")
    assert branch_pos < check_pos < download_pos
