"""Tests for the NemoClaw sandbox adapter (custodian.adapters.nemoclaw).

Covers the three failure-domain distinction the adapter exists to make:
gateway-down vs. timeout vs. an ordinary script failure — previously these
all collapsed into the same opaque subprocess stderr blob. The doctor()
JSON fixture below is the real payload captured live from argobox-lite on
2026-07-14 (see session notes), not a guessed shape.
"""
import subprocess

import pytest

from custodian.adapters.nemoclaw import ExecResult, NemoClawExecutor, SandboxHealth
from custodian.exceptions import (
    SandboxGatewayDownError,
    SandboxScriptError,
    SandboxTimeoutError,
)

REAL_DOCTOR_JSON = {
    "schemaVersion": 1,
    "sandbox": "hermes-hackathon",
    "status": "fail",
    "failed": 1,
    "warnings": 1,
    "checks": [
        {"group": "Host", "label": "CLI build", "status": "ok", "detail": "dist/nemoclaw.js present"},
        {"group": "Host", "label": "Docker daemon", "status": "ok", "detail": "server 29.2.0"},
        {"group": "Gateway", "label": "Docker container", "status": "fail",
         "detail": "openshell-cluster-nemoclaw not found or not inspectable",
         "hint": "run `docker ps --filter name=openshell-cluster-nemoclaw`"},
        {"group": "Gateway", "label": "OpenShell status", "status": "ok", "detail": "connected to nemoclaw"},
        {"group": "Sandbox", "label": "Live sandbox", "status": "ok", "detail": "hermes-hackathon present (Ready)"},
        {"group": "Sandbox", "label": "Agent version", "status": "warn",
         "detail": "OpenClaw v2026.5.16; v2026.5.22 available",
         "hint": "run `nemohermes hermes-hackathon rebuild`"},
    ],
}


@pytest.fixture()
def executor():
    return NemoClawExecutor(sandbox_name="hermes-hackathon", binary_path="/fake/nemohermes")


def test_run_success_returns_ok_execresult(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["/fake/nemohermes", "hermes-hackathon", "exec", "--",
                        "python3", "earn.py", "--amount", "1200.00"]
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = executor.run("earn.py", "--amount", "1200.00")
    assert isinstance(result, ExecResult)
    assert result.ok
    assert result.stdout == "ok"


def test_run_ordinary_script_failure_returns_non_ok_by_default(executor, monkeypatch):
    """A real script error (e.g. the PermissionError bug fixed 2026-07-14)
    must NOT raise by default — it's meaningful data the caller wants to see."""
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="", stderr="Traceback (most recent call last):\nPermissionError: ...")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = executor.run("spend.py", "--amount", "3500.00")
    assert not result.ok
    assert result.returncode == 1
    assert "PermissionError" in result.stderr


def test_run_script_failure_raises_when_check_true(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ValueError: bad input")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SandboxScriptError):
        executor.run("spend.py", check=True)


def test_run_gateway_down_raises_distinct_error(executor, monkeypatch):
    """This is the actual error text reproduced live from argobox-lite on
    2026-07-13 while the sandbox gateway container was down."""
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="",
            stderr="Error:   × transport error\n  ├─▶ tcp connect error\n"
                   "  ├─▶ tcp connect error\n  ╰─▶ Connection refused (os error 111)")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SandboxGatewayDownError):
        executor.run("earn.py", "--amount", "100.00")


def test_run_timeout_raises_distinct_error(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SandboxTimeoutError):
        executor.run("earn.py", timeout=5)


def test_doctor_parses_real_captured_json(executor, monkeypatch):
    import json as _json

    def fake_run(cmd, **kwargs):
        assert cmd == ["/fake/nemohermes", "hermes-hackathon", "doctor", "--json"]
        return subprocess.CompletedProcess(cmd, 1, stdout=_json.dumps(REAL_DOCTOR_JSON), stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    health = executor.doctor()
    assert isinstance(health, SandboxHealth)
    assert not health.ok
    assert health.failed == 1
    assert health.warnings == 1
    gateway_check = next(c for c in health.checks if c.label == "Docker container")
    assert gateway_check.status == "fail"
    assert gateway_check.group == "Gateway"


def test_doctor_unparseable_output_raises_gateway_down(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="connection refused")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SandboxGatewayDownError):
        executor.doctor()


def test_binary_path_prefers_explicit_over_path_lookup():
    executor = NemoClawExecutor(sandbox_name="x", binary_path="/explicit/nemohermes")
    assert executor.binary_path == "/explicit/nemohermes"


def test_binary_path_falls_back_when_not_on_path(monkeypatch):
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which", lambda name: None)
    executor = NemoClawExecutor(sandbox_name="x", fallback_binary_path="/fallback/nemohermes")
    assert executor.binary_path == "/fallback/nemohermes"


def test_read_file_returns_contents_on_success(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["/fake/nemohermes", "hermes-hackathon", "exec", "--", "cat",
                        "/sandbox/.hermes/skills/payments/stripe-spend/state/authority.json"]
        return subprocess.CompletedProcess(cmd, 0, stdout='{"band": "L2"}', stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    content = executor.read_file("/sandbox/.hermes/skills/payments/stripe-spend/state/authority.json")
    assert content == '{"band": "L2"}'


def test_read_file_returns_none_for_missing_file(executor, monkeypatch):
    """Must NOT raise for an ordinary missing file -- every existing caller
    treats 'not there yet' (e.g. no pending escalation) as normal, not an error."""
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="",
                                            stderr="cat: /sandbox/.../pending_code.json: No such file or directory")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert executor.read_file("/sandbox/.../pending_code.json") is None


def test_read_file_raises_on_gateway_down(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd, 1, stdout="",
            stderr="Error:   × transport error\n  ╰─▶ Connection refused (os error 111)")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SandboxGatewayDownError):
        executor.read_file("/sandbox/.../authority.json")


def test_write_file_pipes_content_over_stdin(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["/fake/nemohermes", "hermes-hackathon", "exec", "--",
                        "sh", "-c", 'cat > "$1"', "_", "/sandbox/.../authority.json"]
        assert kwargs["input"] == '{"band": "L2"}'
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    executor.write_file("/sandbox/.../authority.json", '{"band": "L2"}')


def test_write_file_append_uses_shift_redirect(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[6] == 'cat >> "$1"'
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    executor.write_file("/sandbox/.../reasoning_log.jsonl", "line\n", append=True)


def test_write_file_raises_script_error_on_failure(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Permission denied")
    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(SandboxScriptError):
        executor.write_file("/sandbox/.../authority.json", "x")


def test_delete_file_runs_rm_dash_f(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["/fake/nemohermes", "hermes-hackathon", "exec", "--",
                        "rm", "-f", "/sandbox/.../pending_code.json"]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    executor.delete_file("/sandbox/.../pending_code.json")


def test_move_file_runs_mv(executor, monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["/fake/nemohermes", "hermes-hackathon", "exec", "--",
                        "mv", "/sandbox/.../audit_log.jsonl", "/sandbox/.../audit_log.jsonl.archive"]
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    executor.move_file("/sandbox/.../audit_log.jsonl", "/sandbox/.../audit_log.jsonl.archive")
