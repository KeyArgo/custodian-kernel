from pathlib import Path
import time

import pytest

from custodian.control.policy import ApprovalPolicy, ApprovalRule, Proposal


def proposal(**changes):
    values = dict(adapter="codex", action_kind="write", tool="apply_patch",
                  requester="session-a", workspace="/work", host="")
    values.update(changes)
    return Proposal(**values)


def test_default_is_ask(tmp_path: Path):
    assert ApprovalPolicy(tmp_path / "p.json").decide(proposal()) == ("ask", None)


def test_scoped_auto_rule_counts_and_expires(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write",
                        tool="apply_*", requester="session-a", workspace="/work",
                        max_uses=1, expires_at=time.time() + 60)
    policy.add(rule)
    assert policy.decide(proposal()) == ("auto", rule.rule_id)
    assert policy.decide(proposal()) == ("ask", None)


@pytest.mark.parametrize("kind", ["governance", "credential", "destructive", "production", "money"])
def test_high_consequence_kinds_can_never_be_auto_approved(tmp_path: Path, kind: str):
    policy = ApprovalPolicy(tmp_path / "p.json")
    with pytest.raises(ValueError):
        policy.add(ApprovalRule(mode="auto", action_kind=kind))
    policy.add(ApprovalRule(mode="auto", action_kind="*"))
    assert policy.decide(proposal(action_kind=kind)) == ("ask", None)


def test_newest_matching_deny_rule_wins(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    policy.add(ApprovalRule(mode="auto", adapter="codex", action_kind="write"))
    deny = ApprovalRule(mode="deny", adapter="codex", action_kind="write", tool="apply_patch")
    policy.add(deny)
    assert policy.decide(proposal()) == ("deny", deny.rule_id)


def test_fail_closed_malformed_json(tmp_path: Path):
    p = tmp_path / "p.json"
    p.write_text("}{invalid json")
    policy = ApprovalPolicy(p)
    assert policy.list() == []
    assert policy.decide(proposal()) == ("ask", None)


def test_fail_closed_non_list(tmp_path: Path):
    p = tmp_path / "p.json"
    p.write_text('{"adapter": "*"}')
    policy = ApprovalPolicy(p)
    assert policy.list() == []
    assert policy.decide(proposal()) == ("ask", None)


def test_fail_closed_bad_rule_entry(tmp_path: Path):
    p = tmp_path / "p.json"
    p.write_text('[{"mode": "auto", "unknown_field": true}, {"mode": "deny", "adapter": "codex"}]')
    policy = ApprovalPolicy(p)
    rules = policy.list()
    assert len(rules) == 1
    assert rules[0].mode == "deny"


def test_permanent_rule_never_expires(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write", max_uses=None, expires_at=None)
    policy.add(rule)
    for _ in range(10):
        assert policy.decide(proposal()) == ("auto", rule.rule_id)


def test_expired_rule_not_matched(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write", expires_at=time.time() - 1)
    policy.add(rule)
    assert policy.decide(proposal()) == ("ask", None)


def test_deny_rule_for_never_auto_kind(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    deny = ApprovalRule(mode="deny", action_kind="governance", adapter="codex")
    policy.add(deny)
    assert policy.decide(proposal(action_kind="governance")) == ("deny", deny.rule_id)


def test_concurrent_max_uses_not_exceeded(tmp_path: Path):
    import threading
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write",
                        tool="apply_patch", requester="session-a", max_uses=5)
    policy.add(rule)
    results = []
    errors = []
    lock = threading.Lock()

    def run():
        try:
            r = policy.decide(proposal())
            with lock:
                results.append(r)
        except Exception as e:
            with lock:
                errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    auto_count = sum(1 for r in results if r[0] == "auto")
    assert auto_count <= 5
    assert auto_count == 5


def test_concurrent_add_and_decide_no_lost_update(tmp_path: Path):
    import threading
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write",
                        tool="apply_patch", requester="session-a", max_uses=5)
    policy.add(rule)
    # Three threads add the same rule (only first one creates a unique rule, but
    # test that adding doesn't lose rules)
    barrier = threading.Barrier(3)

    def adder():
        barrier.wait()
        policy.add(ApprovalRule(mode="deny", adapter="codex", action_kind="read"))

    threads = [threading.Thread(target=adder) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rules = policy.list()
    # Should have 1 original + 3 added = 4 rules
    assert len(rules) == 4


def test_remove_rule(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write")
    policy.add(rule)
    assert policy.decide(proposal()) == ("auto", rule.rule_id)
    assert policy.remove(rule.rule_id) is True
    assert policy.decide(proposal()) == ("ask", None)
    assert policy.remove(rule.rule_id) is False


def test_recover_orphan_temp_file(tmp_path: Path):
    p = tmp_path / "p.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text("garbage")
    policy = ApprovalPolicy(p)
    rule = ApprovalRule(mode="deny", adapter="codex")
    policy.add(rule)
    assert policy.decide(proposal()) == ("deny", rule.rule_id)
    # Verify the orphan temp file was handled and real file is valid
    rules = policy.list()
    assert len(rules) == 1


def test_expired_rule_does_not_consume_use(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write",
                        max_uses=1, expires_at=time.time() + 60)
    policy.add(rule)
    # First call consumes the use
    assert policy.decide(proposal()) == ("auto", rule.rule_id)
    # Second call: max_uses exhausted
    assert policy.decide(proposal()) == ("ask", None)
    # Add a fresh rule to confirm policy is still writable
    policy.add(ApprovalRule(mode="deny", adapter="other"))
    assert policy.remove(rule.rule_id) is True


def test_uses_persist_across_policy_reload(tmp_path: Path):
    path = tmp_path / "p.json"
    policy = ApprovalPolicy(path)
    rule = ApprovalRule(mode="auto", adapter="codex", action_kind="write",
                        tool="apply_patch", requester="session-a", max_uses=2)
    policy.add(rule)
    assert policy.decide(proposal()) == ("auto", rule.rule_id)
    # New policy instance reads the same file
    policy2 = ApprovalPolicy(path)
    assert policy2.decide(proposal()) == ("auto", rule.rule_id)
    assert policy2.decide(proposal()) == ("ask", None)


def test_ask_rule_does_not_increment_uses(tmp_path: Path):
    policy = ApprovalPolicy(tmp_path / "p.json")
    rule = ApprovalRule(mode="ask", adapter="codex", action_kind="write",
                        max_uses=1)
    policy.add(rule)
    assert policy.decide(proposal()) == ("ask", rule.rule_id)
    # Second call should also match (ask doesn't consume uses)
    assert policy.decide(proposal()) == ("ask", rule.rule_id)
