from custodian.codex_guard import mcp_server
from custodian.control.policy import ApprovalPolicy, ApprovalRule


def call(tmp_path, monkeypatch, kind="network"):
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(tmp_path))
    return mcp_server.handle("tools/call", {"name": "guard_action", "arguments": {
        "tool": "test-tool", "action_kind": kind, "arguments": {},
        "workspace": str(tmp_path), "requester": "test-session",
    }})["structuredContent"]


def test_scoped_network_policy_mints_and_consumes_exact_approval(tmp_path, monkeypatch):
    policy = ApprovalPolicy(tmp_path / "approval-policy.json")
    policy.add(ApprovalRule(mode="auto", adapter="codex", action_kind="network",
                            tool="test-tool", max_uses=1))
    result = call(tmp_path, monkeypatch)
    assert result["verdict"] == "approved"
    assert result["policy_rule_id"]
    from custodian.codex_guard.approvals import ApprovalStore
    record = ApprovalStore(tmp_path).get(result["approval_id"])
    assert record.status == "consumed"


def test_policy_can_auto_approve_escalated_low_risk_class_only(tmp_path, monkeypatch):
    # Governance can never auto. This test documents the immutable boundary.
    policy = ApprovalPolicy(tmp_path / "approval-policy.json")
    policy.add(ApprovalRule(mode="auto", adapter="codex", action_kind="*", tool="test-tool"))
    result = call(tmp_path, monkeypatch, kind="governance")
    assert result["verdict"] == "escalation_required"
