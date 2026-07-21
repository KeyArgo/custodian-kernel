"""Regression tests for 6 bugs found in dashboard/api/triage.py and
triage_live.py during a full adversarial review, never fixed until now
(a first pass fixed other files this same session but missed this one):

1. GET /api/v1/triage/case/<id> had no auth AND no rate limiting, despite
   being able to trigger a real billed NIM/Modal call (the cloud pack's
   auto_provision path) on every hit -- an unauthenticated visitor could
   loop this endpoint to run up real usage indefinitely.
2. The NVIDIA API key was briefly written to a predictable path with
   default (world-readable) permissions before being read back and deleted.
3. No rate limiting on /custom or /run?live=1 despite making real LLM calls.
4. _load_case()'s case_id had no path-boundary check -- "../account_ledger"
   style values escaped the corpus directory.
5. triage_live.py's /live accepted NaN/Infinity amounts (both parse
   successfully and are truthy in Python, so the `or None` guard missed
   them), serializing invalid (non-RFC-8259) JSON to the visitor.
6. The spend-log writer wrote to a local file invisible to hermes.py's
   sandboxed audit-log reader, so real spend triggered via this demo never
   appeared in the publicly-displayed P&L total despite a comment claiming
   otherwise.
"""
from __future__ import annotations

import sys
from collections import defaultdict, deque
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def client():
    from app import app
    return app.test_client()


def test_case_by_id_is_rate_limited(client):
    import api.triage as triage

    with patch.object(triage, "_request_log", defaultdict(deque)):
        statuses = []
        for _ in range(triage._RATE_LIMIT_MAX_REQUESTS + 1):
            r = client.get("/api/v1/triage/case/01-modal-autoprovision?pack=cloud")
            statuses.append(r.status_code)
    assert 429 in statuses, "case_by_id must eventually rate-limit a flood from one IP"


def test_run_is_rate_limited(client):
    import api.triage as triage

    with patch.object(triage, "_request_log", defaultdict(deque)):
        statuses = []
        for _ in range(triage._RATE_LIMIT_MAX_REQUESTS + 1):
            r = client.get("/api/v1/triage/run?case_id=01-modal-autoprovision&pack=cloud")
            statuses.append(r.status_code)
    assert 429 in statuses


def test_custom_is_rate_limited(client):
    import api.triage as triage

    with patch.object(triage, "_request_log", defaultdict(deque)):
        statuses = []
        for _ in range(triage._RATE_LIMIT_MAX_REQUESTS + 1):
            r = client.post("/api/v1/triage/custom", json={
                "pack": "refunds", "customer_email": "it never arrived",
            })
            statuses.append(r.status_code)
    assert 429 in statuses


def _write_nim_key_file(path, value):
    """Mirrors the exact write sequence in _execute_provision()."""
    import os
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if os.name != "nt":
        os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"NVIDIA_API_KEY={value}\n")


def test_nim_key_file_is_written_with_restrictive_permissions(tmp_path):
    """Regression: Path.write_text() left the key file at default
    (typically 0644, world-readable) permissions briefly."""
    fake_path = tmp_path / "nvidia_nim_key.env"
    _write_nim_key_file(fake_path, "sk-test-12345")
    mode = fake_path.stat().st_mode & 0o777
    assert mode == 0o600, f"key file must be 0600, was {oct(mode)}"


@pytest.mark.skipif(__import__("os").name == "nt", reason="posix permission semantics")
def test_nim_key_file_is_re_locked_down_even_if_a_stale_file_already_exists(tmp_path):
    """Regression found by adversarial re-verification: os.open's mode
    argument only applies when O_CREAT actually creates a NEW inode -- a
    stale file left over from a prior hard-killed run (SIGKILL/OOM bypass
    the surrounding finally: unlink()) with looser permissions kept those
    looser permissions even after the "fixed" write. os.fchmod() after
    opening closes this regardless of whether the file was just created or
    already existed."""
    fake_path = tmp_path / "nvidia_nim_key.env"
    fake_path.write_text("stale content from a prior crashed run\n")
    fake_path.chmod(0o644)
    assert fake_path.stat().st_mode & 0o777 == 0o644, "sanity check: the stale file starts loose"

    _write_nim_key_file(fake_path, "sk-test-12345")

    mode = fake_path.stat().st_mode & 0o777
    assert mode == 0o600, f"key file must be re-locked to 0600 even over a stale file, was {oct(mode)}"


@pytest.mark.parametrize("case_id", [
    "../account_ledger",
    "..%2Faccount_ledger",
    "sub/dir",
    "a\\b",
])
def test_load_case_rejects_path_traversal(case_id):
    import api.triage as triage
    corpus_dir = Path(__file__).resolve().parents[2] / "custodian" / "packs" / "refunds" / "corpus"
    assert triage._load_case(corpus_dir, case_id) is None


def test_load_case_still_loads_a_real_case():
    import api.triage as triage
    corpus_dir = Path(__file__).resolve().parents[2] / "custodian" / "packs" / "refunds" / "corpus"
    real_case_id = next(corpus_dir.glob("*.json")).stem
    assert triage._load_case(corpus_dir, real_case_id) is not None


@pytest.mark.parametrize("case_id", [
    "foo\x00bar",
    "x" * 5000,
])
def test_load_case_fails_closed_on_a_malformed_case_id_instead_of_500(case_id):
    """Regression found by adversarial re-verification: a null byte or an
    oversized case_id made Path.resolve() itself raise (ValueError/OSError)
    instead of just failing to match a file -- an uncaught 500 instead of
    the intended fail-closed 404. Same bug class this same commit already
    fixed in fence_config() elsewhere in the codebase."""
    import api.triage as triage
    corpus_dir = Path(__file__).resolve().parents[2] / "custodian" / "packs" / "refunds" / "corpus"
    assert triage._load_case(corpus_dir, case_id) is None


def test_run_endpoint_does_not_500_on_a_null_byte_case_id(client):
    """End-to-end: the same malformed case_id reaching the actual route
    must produce a clean 404, not a raw 500 error page."""
    resp = client.get("/api/v1/triage/run", query_string={"case_id": "foo\x00bar"})
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_amount", ["nan", "inf", "-inf", "Infinity"])
def test_triage_live_rejects_nonfinite_amount(client, bad_amount):
    resp = client.post("/api/v1/triage/live", json={
        "customer_id": "cus_marcus", "order_id": "ord_6006", "amount": bad_amount,
    })
    assert resp.status_code == 400
    assert "finite" in resp.get_json()["error"]


def test_triage_live_still_accepts_a_normal_amount(client):
    resp = client.post("/api/v1/triage/live", json={
        "customer_id": "cus_marcus", "order_id": "ord_6006", "amount": "42.5",
    })
    assert resp.status_code == 200


def test_log_spend_writes_through_the_sandbox_not_a_local_file(tmp_path):
    """Regression: _log_spend used to write to a local Path.open("a") that
    hermes.py's sandboxed audit-log reader could never see. Confirm it now
    calls _sandbox.write_file (the same mechanism operator.py/hermes.py use)
    instead of touching the local filesystem directly."""
    import api.triage as triage

    calls = []

    def _fake_write_file(path, content, append=False):
        calls.append((path, content, append))

    with patch.object(triage._sandbox, "write_file", _fake_write_file):
        triage._log_spend("case-1", "nvidia-nim", 1.2, "test provision")

    assert len(calls) == 1
    path, content, append = calls[0]
    assert path == triage._AUDIT_LOG_PATH
    assert append is True
    assert "case-1" in content
