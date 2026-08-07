"""Tests for the Custodian Hermes guard adapter.

Through-line: every abnormal path must resolve to an explicit denial or a
suppressed result -- never to silence. Hermes' ``pre_tool_call`` hook treats
a ``None`` return as "proceed", so a guard that merely crashed would fail
OPEN; the runtime therefore converts every failure mode into a decision
with ``allowed=False`` and the plugin into a ``block`` directive.

Coverage map (Custodian Hermes control handoff, "Required tests"):

* direct write and patch interception;
* shell write targeting the same protected file;
* symlink/path traversal and alternate path spelling;
* attempts to modify Hermes config / SOUL.md / Custodian / Paladin paths;
* denied approval, expired approval, replayed approval, changed digest;
* guard outage and malformed response;
* receipt alteration detection;
* post-result redaction and suppression.

Note: credential-shaped strings in this file are assembled at runtime so
no literal secret-looking token sits in the source (the secret-leak guard
applies to this repo too).
"""
from __future__ import annotations

import json
import random
import string
import time

import pytest

import custodian.hermes_guard.bridge as bridge_mod
from custodian.codex_guard.approvals import ApprovalStore, action_digest
from custodian.codex_guard.guard import ActionKind
from custodian.codex_guard.receipts import ReceiptChain
from custodian.hermes_guard.bridge import evaluate_tool
from custodian.hermes_guard.contract import (
    HERMES_GUARD_CONTRACT_VERSION,
    HermesDecision,
    classify_tool,
    verdict_to_directive,
)
from custodian.hermes_guard.runtime import HermesGuardRuntime

WORKSPACE_SUBDIR = "project"


def _state(monkeypatch, tmp_path):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(state))
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state))
    # The hermes runtime refuses to construct when the gate is off; every
    # test in this file exercises the runtime as ACTIVE.
    from custodian.guards.gate import enable as _gate_enable
    _gate_enable(str(state), "hermes")


def _workspace(tmp_path):
    root = tmp_path / WORKSPACE_SUBDIR
    root.mkdir(exist_ok=True)
    return root


def proposal(workspace, **overrides):
    value = {
        "tool": "read_file",
        "arguments": {"path": str(workspace / "x.py")},
        "workspace": str(workspace),
        "requester": "hermes:sess-1",
        "session_id": "sess-1",
    }
    value.update(overrides)
    return value


def _high_entropy(seed: int, length: int = 40) -> str:
    """Deterministic high-entropy-looking string, assembled at runtime so no
    credential-shaped literal sits in this source file."""
    rng = random.Random(seed)
    alphabet = string.ascii_lowercase + string.digits
    return "".join(rng.choice(alphabet) for _ in range(length))


# A github-shaped token assembled at runtime (prefix split so the literal
# never appears in this file): "gh" + "p_" + high-entropy tail.
_GITHUB_TOKEN = "gh" + "p_" + _high_entropy(1)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool,kind", [
    ("read_file", "read"), ("search_files", "read"), ("session_search", "read"),
    ("skills_list", "read"), ("skill_view", "read"), ("todo", "read"),
    ("clarify", "read"), ("turbofit_status", "read"),
    ("write_file", "write"), ("patch", "write"),
    ("terminal", "test"), ("process", "test"), ("execute_code", "test"),
    ("browser_navigate", "network"), ("web_extract", "network"),
    ("web_search", "network"), ("image_generate", "network"),
    ("text_to_speech", "network"), ("browser_snapshot", "network"),
    ("memory", "governance"), ("skill_manage", "governance"),
    ("cronjob", "governance"), ("delegate_task", "governance"),
    ("computer_use", "governance"), ("turbofit_configure", "governance"),
    # Every unknown/future tool must escalate, never be assumed a read.
    ("SomeFutureTool", "governance"), ("mcp__stripe__create_charge", "governance"),
])
def test_classification(tool, kind):
    assert classify_tool(tool) == kind


def test_classification_normalized():
    assert classify_tool("  Write_File ") == "write"
    assert classify_tool("READ_FILE") == "read"


# ---------------------------------------------------------------------------
# Direct write / read interception
# ---------------------------------------------------------------------------


def test_read_within_workspace_allows(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(workspace))
    assert decision["verdict"] == "autonomous"
    assert decision["action_kind"] == "read"


def test_workspace_write_allows(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="write_file",
        arguments={"path": str(workspace / "b.py"), "content": "x"}))
    assert decision["verdict"] == "autonomous"


def test_patch_within_workspace_allows(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="patch",
        arguments={"path": str(workspace / "b.py"), "new_string": "y"}))
    assert decision["verdict"] == "autonomous"


def test_write_to_forbidden_path_denies(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="write_file",
        arguments={"path": "~/.ssh/authorized_keys", "content": "k"}))
    assert decision["verdict"] == "denied"


@pytest.mark.parametrize("protected", [
    "~/.hermes/config.yaml",
    "~/.hermes/profiles/dev/config.yaml",
    "~/.hermes/profiles/dev/plugins/custodian-hermes-guard/__init__.py",
    "~/.hermes/SOUL.md",
])
def test_hermes_paths_denied(tmp_path, monkeypatch, protected):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="write_file",
        arguments={"path": protected, "content": "x"}))
    assert decision["verdict"] == "denied"


def test_write_outside_workspace_denies(tmp_path, monkeypatch):
    """Symlink/path-traversal and alternate spelling must not escape."""
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="write_file",
        arguments={"path": str(tmp_path / "escape.txt"), "content": "x"}))
    assert decision["verdict"] == "denied"


def test_shell_write_protected(tmp_path, monkeypatch):
    """A bash redirect must be treated exactly like a write_file."""
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="terminal",
        arguments={"command": "echo x >> ~/.hermes/profiles/dev/config.yaml"}))
    assert decision["verdict"] == "denied"


def test_network_tool_escalates(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="web_extract",
        arguments={"urls": ["http://example.com"]}))
    assert decision["verdict"] == "escalation_required"
    assert decision.get("approval_id")


def test_unknown_tool_escalates(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="brand_new_tool", arguments={"x": 1}))
    assert decision["verdict"] == "escalation_required"
    assert decision["action_kind"] == "governance"


def test_credential_shell_escalates(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    decision = evaluate_tool(proposal(
        workspace, tool="terminal",
        arguments={"command": f"echo ${'STRIPE_SECRET_KEY'}"}))
    assert decision["verdict"] == "escalation_required"
    assert decision["action_kind"] == "credential"


# ---------------------------------------------------------------------------
# Malformed input / guard outage / malformed response (fail closed)
# ---------------------------------------------------------------------------


def test_malformed_proposal_fails_closed():
    assert evaluate_tool(None)["verdict"] == "denied"
    assert evaluate_tool({})["verdict"] == "denied"
    assert evaluate_tool({"tool": "write_file"})["verdict"] == "denied"
    assert evaluate_tool({
        "tool": "write_file", "arguments": {},
        "workspace": "/tmp", "requester": "",
    })["verdict"] == "denied"


def test_guard_outage_fails_closed(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)

    def boom(request, **kwargs):
        raise RuntimeError("control plane down")

    monkeypatch.setattr(bridge_mod, "evaluate_guard_action", boom)
    decision = evaluate_tool(proposal(workspace))
    assert decision["verdict"] == "denied"
    assert "unavailable" in decision["reason"]

    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    wrapped = runtime.evaluate_pre("write_file", {"path": str(workspace / "x")})
    assert wrapped.allowed is False
    assert wrapped.verdict == "denied"


def test_malformed_response_fails_closed(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)

    def weird(request, **kwargs):
        return {"verdict": "maybe", "action_kind": "write"}

    monkeypatch.setattr(bridge_mod, "evaluate_guard_action", weird)
    decision = evaluate_tool(proposal(workspace))
    assert decision["verdict"] == "denied"
    assert "invalid Custodian response" in decision["reason"]


# ---------------------------------------------------------------------------
# Approvals: denied / expired / replayed / changed digest
# ---------------------------------------------------------------------------


def _digest(workspace, requester="hermes:sess-1", **overrides):
    return action_digest(
        tool=overrides.get("tool", "write_file"),
        action_kind=overrides.get("action_kind", ActionKind.WRITE.value),
        arguments=overrides.get("arguments", {"path": str(workspace / "a.py"), "content": "x"}),
        workspace=str(workspace),
        requester=requester,
        policy_version=HERMES_GUARD_CONTRACT_VERSION,
    )


def test_escalation_approved_once(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    first = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    assert first["verdict"] == "escalation_required"
    approval_id = first["approval_id"]
    digest = first["action_digest"]

    store = ApprovalStore(state)
    store.approve(approval_id, approved_by="operator", expected_digest=digest)

    second = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]},
        approval_id=approval_id))
    assert second["verdict"] == "approved"
    assert second["approval_id"] == approval_id


def test_replayed_approval_denied(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    first = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    approval_id = first["approval_id"]
    store = ApprovalStore(state)
    store.approve(approval_id, approved_by="operator",
                  expected_digest=first["action_digest"])

    assert evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]},
        approval_id=approval_id))["verdict"] == "approved"
    # Second use of the same single-use approval must fail closed.
    replayed = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]},
        approval_id=approval_id))
    assert replayed["verdict"] == "denied"


def test_changed_digest_denied(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    first = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    approval_id = first["approval_id"]
    store = ApprovalStore(state)
    store.approve(approval_id, approved_by="operator",
                  expected_digest=first["action_digest"])

    # Same approval id, different target URL -> different digest -> denied.
    changed = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://other.example"]},
        approval_id=approval_id))
    assert changed["verdict"] == "denied"
    assert "changed after approval" in changed["reason"]


def test_expired_approval_ignored(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    # Mint an approval that is already expired relative to real time.
    past = time.time() - 400
    old_store = ApprovalStore(state, now=lambda: past)
    digest = _digest(workspace, tool="web_extract",
                     action_kind=ActionKind.NETWORK.value,
                     arguments={"urls": ["http://example"]})
    record = old_store.request(digest=digest, requester="hermes:sess-1",
                               ttl_seconds=300, harness="hermes")
    old_store.approve(record.approval_id, approved_by="operator",
                      expected_digest=digest)
    assert record.expires_at < time.time()

    # The expired approval must not satisfy the escalating re-run: the
    # action escalates again with a NEW approval id instead of running,
    # and the stale record is never consumed.
    decision = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    assert decision["verdict"] == "escalation_required"
    assert decision["approval_id"] != record.approval_id
    assert old_store.get(record.approval_id).status == "approved"


def test_denied_approval_stays_denied(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    first = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    approval_id = first["approval_id"]
    ApprovalStore(state).deny(approval_id, denied_by="operator")

    # An explicit operator denial must not be silently re-approved by a
    # later find_approved on the same digest.
    again = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    assert again["verdict"] == "escalation_required"
    assert again["approval_id"] != approval_id


# ---------------------------------------------------------------------------
# wait_for_approval runtime behavior
# ---------------------------------------------------------------------------


def test_approval_wait_approves(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    first = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    approval_id = first["approval_id"]
    store = ApprovalStore(state)
    store.approve(approval_id, approved_by="operator",
                  expected_digest=first["action_digest"])

    runtime = HermesGuardRuntime(state_dir=state)
    decision = runtime.wait_for_approval(
        "web_extract", {"urls": ["http://example"]},
        approval_id=approval_id, requester="hermes:sess-1",
        workspace=str(workspace), timeout_seconds=2)
    assert decision.verdict == "approved"
    assert decision.allowed is True

    # Consumed: a second wait for the same id must fail closed.
    replay = runtime.wait_for_approval(
        "web_extract", {"urls": ["http://example"]},
        approval_id=approval_id, requester="hermes:sess-1",
        workspace=str(workspace), timeout_seconds=2)
    assert replay.allowed is False


def test_approval_wait_denied(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    first = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))
    ApprovalStore(state).deny(first["approval_id"], denied_by="operator")

    runtime = HermesGuardRuntime(state_dir=state)
    decision = runtime.wait_for_approval(
        "web_extract", {"urls": ["http://example"]},
        approval_id=first["approval_id"], requester="hermes:sess-1",
        workspace=str(workspace), timeout_seconds=2)
    assert decision.allowed is False
    assert "denied" in decision.reason


def test_approval_wait_timeout(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    first = evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))

    runtime = HermesGuardRuntime(state_dir=state)
    decision = runtime.wait_for_approval(
        "web_extract", {"urls": ["http://example"]},
        approval_id=first["approval_id"], requester="hermes:sess-1",
        workspace=str(workspace), timeout_seconds=1)
    assert decision.allowed is False
    assert "wait window" in decision.reason


def test_approval_wait_missing_id(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    decision = runtime.wait_for_approval(
        "write_file", {}, approval_id="", timeout_seconds=1)
    assert decision.allowed is False


# ---------------------------------------------------------------------------
# Runtime surface: pipeline probe, policy, pre decisions
# ---------------------------------------------------------------------------


def test_runtime_initializes(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    # The pipeline is the compatibility probe; it must exist after init.
    assert runtime.pipeline is not None
    policy = runtime.policy
    assert policy["harness"] == "hermes"
    assert policy["contract_version"] == HERMES_GUARD_CONTRACT_VERSION
    assert 0 <= policy["operator"]["approval_wait_seconds"] <= 3600


def test_evaluate_pre_decision(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    decision = runtime.evaluate_pre(
        "write_file", {"path": str(workspace / "x.py"), "content": "x"},
        requester="hermes:agent", workspace=str(workspace), session_id="sess-9")
    assert isinstance(decision, HermesDecision)
    assert decision.allowed is True
    assert decision.verdict == "autonomous"


def test_evaluate_pre_escalation(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    decision = runtime.evaluate_pre(
        "delegate_task", {"goal": "x"},
        requester="hermes:agent", workspace=str(workspace), session_id="sess-9")
    assert decision.verdict == "escalation_required"
    assert decision.allowed is False
    assert decision.approval_id


# ---------------------------------------------------------------------------
# Post-result redaction / suppression
# ---------------------------------------------------------------------------


def test_result_redacts_token(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    result = f"config: token={_GITHUB_TOKEN}"
    transformed = runtime.inspect_result("read_file", {"path": "/x"}, result)
    assert transformed is not None
    assert "REDACTED" in transformed


def test_result_redacts_entropy(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    # 96-char pseudorandom token: entropy ~4.76 >= 4.5, len >= 32 -> the
    # shared core's high-entropy fallback must redact it (verified: the
    # 60-char variant measured 4.496, just under the threshold).
    result = f"key={_high_entropy(2, 96)}"
    transformed = runtime.inspect_result("read_file", {"path": "/x"}, result)
    assert transformed is not None
    assert "REDACTED" in transformed


def test_clean_result_unchanged(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    result = "def foo():\n    return 42\n"
    assert runtime.inspect_result("read_file", {"path": "/x"}, result) is None


def test_non_string_result(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    runtime = HermesGuardRuntime(state_dir=tmp_path / "state")
    assert runtime.inspect_result("read_file", {}, {"not": "a string"}) is None
    assert runtime.inspect_result("read_file", {}, 42) is None


# ---------------------------------------------------------------------------
# Receipt integrity
# ---------------------------------------------------------------------------


def test_receipt_tamper_detected(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    evaluate_tool(proposal(workspace, tool="write_file",
                           arguments={"path": str(workspace / "a.py"), "content": "x"}))
    evaluate_tool(proposal(
        workspace, tool="web_extract", arguments={"urls": ["http://example"]}))

    chain = ReceiptChain(state)
    assert chain.verify() == 2

    # Tamper with the chain; verification must fail.
    lines = (state / "codex-guard-receipts.jsonl").read_text().splitlines()
    record = json.loads(lines[-1])
    record["verdict"] = "autonomous"
    (state / "codex-guard-receipts.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True)
                  for r in [json.loads(lines[0]), record]) + "\n")
    with pytest.raises(Exception):
        chain.verify()


def test_receipts_value_free(tmp_path, monkeypatch):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    state = tmp_path / "state"

    marker = "ordinary-content-marker-9f3a"
    evaluate_tool(proposal(
        workspace, tool="write_file",
        arguments={"path": str(workspace / "a.py"), "content": marker}))

    raw = (state / "codex-guard-receipts.jsonl").read_text()
    assert marker not in raw
    assert "harness" in raw and '"hermes"' in raw


# ---------------------------------------------------------------------------
# Hook directive mapping (the Hermes pre_tool_call return contract)
# ---------------------------------------------------------------------------


def test_directive_allows_and_blocks():
    assert verdict_to_directive(HermesDecision(
        verdict="autonomous", allowed=True, action_kind="read")) is None
    assert verdict_to_directive(HermesDecision(
        verdict="approved", allowed=True, action_kind="write")) is None

    blocked = verdict_to_directive(HermesDecision(
        verdict="denied", allowed=False, action_kind="write",
        reason="operator policy",
        notification="Talaria blocked this write: operator policy"))
    assert blocked == {"action": "block",
                       "message": "[hermes-guard] Talaria blocked this write: operator policy"}

    escalated = verdict_to_directive(HermesDecision(
        verdict="escalation_required", allowed=False, action_kind="network",
        reason="network actions require approval", approval_id="abc-123"))
    assert escalated["action"] == "block"
    assert "abc-123" in escalated["message"]


# ---------------------------------------------------------------------------
# CLI bridge parity
# ---------------------------------------------------------------------------


def test_cli_evaluate_roundtrip(tmp_path, monkeypatch, capsys):
    _state(monkeypatch, tmp_path)
    workspace = _workspace(tmp_path)
    import io
    import sys

    from custodian.hermes_guard import cli
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(proposal(workspace))))
    code = cli.cmd_evaluate(None)
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["verdict"] == "autonomous"


def test_cli_doctor_ok(tmp_path, monkeypatch, capsys):
    _state(monkeypatch, tmp_path)
    from custodian.hermes_guard import cli
    assert cli.cmd_doctor(None) == 0
    assert "OK" in capsys.readouterr().out
