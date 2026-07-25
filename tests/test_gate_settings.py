from pathlib import Path

from custodian.cli.main import main
from custodian.control.policy import ApprovalPolicy, ApprovalRule, Proposal
from custodian.control.settings import ControlSettingsStore
from custodian.codex_guard.mcp_server import _text_result


def _proposal(kind: str) -> Proposal:
    return Proposal(
        adapter="codex", action_kind=kind, tool="shell",
        requester="test", workspace="/tmp/project",
    )


def test_protected_is_safe_default(tmp_path):
    policy = ApprovalPolicy(tmp_path / "approval-policy.json")
    policy.add(ApprovalRule(mode="auto", action_kind="*"))
    assert policy.decide(_proposal("write"))[0] == "auto"
    assert policy.decide(_proposal("governance"))[0] == "ask"


def test_developer_open_allows_matching_high_risk_rule(tmp_path):
    state = tmp_path
    policy = ApprovalPolicy(state / "approval-policy.json")
    policy.add(ApprovalRule(mode="auto", action_kind="*"))
    assert main(["gates", "open", "--state-dir", str(state)]) == 0
    assert policy.decide(_proposal("governance"))[0] == "auto"


def test_quiet_keeps_independent_enforcement_setting(tmp_path):
    assert main(["gates", "open", "--state-dir", str(tmp_path)]) == 0
    assert main([
        "gates", "notifications", "quiet", "--state-dir", str(tmp_path)
    ]) == 0
    settings = ControlSettingsStore(
        Path(tmp_path) / "control-settings.json"
    ).load()
    assert settings.enforcement == "open"
    assert settings.visibility == "quiet"


def test_quiet_mcp_result_omits_routine_explanation(monkeypatch, tmp_path):
    monkeypatch.setenv("CUSTODIAN_CODEX_GUARD_STATE_DIR", str(tmp_path))
    assert main([
        "gates", "notifications", "quiet", "--state-dir", str(tmp_path)
    ]) == 0
    result = _text_result({
        "verdict": "autonomous",
        "action_kind": "read",
        "reason": "routine explanation",
        "enforcement_required": True,
        "receipt": {"chain_mac": "abc"},
    })
    assert "reason" not in result["structuredContent"]
    assert result["structuredContent"]["verdict"] == "autonomous"
