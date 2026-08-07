"""Integration tests for the repository-owned Hermes plugin module.

These tests call the plugin's pre_tool_call and transform_tool_result hook
functions directly with realistic Hermes Agent kwargs, proving the
end-to-end chain: Hermes hook call -> plugin -> guard runtime -> shared
decision engine -> block/allowed directive -> Hermes response contract.

No Hermes process is spawned; the hooks are plain Python functions.
Credential-shaped test strings are assembled at runtime so no literal
secret sits in this source file.
"""
from __future__ import annotations

import string
import random
import json
import os

import pytest

from custodian.hermes_guard import plugin as plugin_mod


def _state_dir(tmp_path):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    return state


@pytest.fixture(autouse=True)
def _enable_hermes_guard(monkeypatch, tmp_path):
    """Every test in this file exercises the hermes guard as ACTIVE; the
    gate must be turned on for the runtime to construct."""
    state = _state_dir(tmp_path)
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state))
    from custodian.guards.gate import enable as _gate_enable
    _gate_enable(str(state), "hermes")


def _patch_env(monkeypatch, state):
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(state))
    # Short approval window so escalation tests don't block the suite.
    monkeypatch.setenv("TALARIA_APPROVAL_WAIT_SECONDS", "1")


def _high_entropy(seed: int, length: int = 40) -> str:
    rng = random.Random(seed)
    alphabet = string.ascii_lowercase + string.digits
    return "".join(rng.choice(alphabet) for _ in range(length))


_GITHUB_TOKEN = "gh" + "p_" + _high_entropy(1)

# Standard Hermes hook kwargs shape (session_id, task_id, etc.)
_CONTEXT = {
    "session_id": "sess-int-1",
    "task_id": "task-int-1",
    "tool_call_id": "tcid-001",
    "turn_id": "turn-001",
    "api_request_id": "req-001",
    "middleware_trace": [],
}


def _pre(tool_name, args, **extra):
    ctx = dict(_CONTEXT)
    ctx.update(extra)
    return plugin_mod._on_pre_tool_call(tool_name, args, **ctx)


def _post(tool_name, args, result):
    return plugin_mod._on_transform_tool_result(tool_name, args, result, **_CONTEXT)


# ---------------------------------------------------------------------------
# pre_tool_call: allowed actions
# ---------------------------------------------------------------------------


def test_read_in_workspace_allows(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    workspace = tmp_path / "project"
    workspace.mkdir()
    result = _pre("read_file", {"path": str(workspace / "x.py")}, workspace=str(workspace))
    assert result is None  # None means Hermes proceeds


def test_write_in_workspace_allows(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    workspace = tmp_path / "project"
    workspace.mkdir()
    result = _pre("write_file", {"path": str(workspace / "x.py"), "content": "y"},
                  workspace=str(workspace))
    assert result is None


def test_todo_allows(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _pre("todo", {"todos": [{"id": "1", "content": "z", "status": "pending"}]})
    assert result is None


# ---------------------------------------------------------------------------
# pre_tool_call: blocked actions
# ---------------------------------------------------------------------------


def test_write_to_hermes_sooul_md_blocked(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _pre("write_file", {"path": "~/.hermes/SOUL.md", "content": "malicious"})
    assert isinstance(result, dict)
    assert result["action"] == "block"
    assert "[hermes-guard]" in result["message"]


def test_write_to_hermes_config_blocked(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _pre("write_file", {"path": "~/.hermes/profiles/dev/config.yaml", "content": "x"})
    assert isinstance(result, dict)
    assert result["action"] == "block"


def test_shell_redirect_to_hermes_blocked(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _pre("terminal", {"command": "echo x >> ~/.hermes/profiles/dev/config.yaml"})
    assert isinstance(result, dict)
    assert result["action"] == "block"


def test_forbidden_path_blocked(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _pre("write_file", {"path": "~/.ssh/authorized_keys", "content": "k"})
    assert isinstance(result, dict)
    assert result["action"] == "block"


def test_governance_tool_blocked_without_approval(tmp_path, monkeypatch):
    """delegate_task is governance -> escalation -> wait_for_approval
    times out (TALARIA_APPROVAL_WAIT_SECONDS=1) -> blocked."""
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _pre("delegate_task", {"goal": "delete everything"})
    assert isinstance(result, dict)
    assert result["action"] == "block"


def test_network_tool_blocked_without_approval(tmp_path, monkeypatch):
    """web_extract is network -> escalation -> timeout -> blocked."""
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _pre("web_extract", {"urls": ["http://example.com"]})
    assert isinstance(result, dict)
    assert result["action"] == "block"


# ---------------------------------------------------------------------------
# transform_tool_result: redaction / suppression / pass-through
# ---------------------------------------------------------------------------


def test_result_redacts_token_leak(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _post("read_file", {"path": "/x"}, f"config: token={_GITHUB_TOKEN}")
    assert isinstance(result, str)
    assert "gh" + "p_" not in result  # redacted
    assert "REDACTED" in result


def test_result_redacts_high_entropy(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    payload = f"key={_high_entropy(3, 96)}"
    result = _post("read_file", {"path": "/x"}, payload)
    assert isinstance(result, str)
    assert "REDACTED" in result


def test_clean_result_unchanged(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    result = _post("read_file", {"path": "/x"}, "def foo():\n    return 42\n")
    assert result is None  # None means Hermes proceeds with original result


def test_non_string_result_unchanged(tmp_path, monkeypatch):
    _patch_env(monkeypatch, _state_dir(tmp_path))
    assert _post("search_files", {}, {"paths": ["/x"]}) is None
    assert _post("read_file", {}, 42) is None


def test_missing_import_triggers_fail_closed(monkeypatch, tmp_path):
    """When custodian cannot import at all, both hooks block / suppress."""
    _patch_env(monkeypatch, _state_dir(tmp_path))
    # Simulate module re-init with a broken import.
    monkeypatch.setattr(plugin_mod, "_IMPORT_ERROR", RuntimeError("simulated"))
    assert _pre("read_file", {"path": "/tmp/x"}) == {
        "action": "block",
        "message": "[hermes-guard] unavailable; tool call blocked (kernel import failed)",
    }
    assert _post("read_file", {}, "hello") == "[hermes-guard] output suppressed: guard unavailable"
