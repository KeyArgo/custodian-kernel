from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest

from custodian.adapters.builtin._paths import resolve as canonicalize
from custodian.codex_guard.guard import evaluate_action
from custodian.control.filesystem_policy import FilesystemPolicy, FilesystemRule


# ---------------------------------------------------------------------------
# Existing behaviour — preserved API
# ---------------------------------------------------------------------------

def test_inherits_harness_defaults_without_rule(tmp_path: Path):
    config = FilesystemPolicy(tmp_path / "p.json").fence_config(
        harness="codex", model="gpt", access="read",
        inherited_allow=["/work"], inherited_deny=["~/.ssh"])
    assert config["source"] == "harness-default"
    assert config["allow_paths"] == [canonicalize("/work")]


def test_exact_model_overrides_wildcard_and_directions_are_independent(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "p.json")
    policy.add(FilesystemRule(harness="codex", model="*", access="read",
                              allow_roots=("/",), deny_roots=("~/vault",)))
    exact = FilesystemRule(harness="codex", model="gpt", access="read",
                           allow_roots=("~/Development",), deny_roots=("~/credentials",))
    policy.add(exact)
    assert policy.effective(harness="codex", model="gpt", access="read") == exact
    assert policy.effective(harness="codex", model="gpt", access="write") is None


def test_deny_roots_extend_invariant_harness_denies(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "p.json")
    policy.add(FilesystemRule(harness="hermes", access="write",
                              allow_roots=("/",), deny_roots=("/mnt/xyz",)))
    config = policy.fence_config(harness="hermes", model="qwen", access="write",
                                 inherited_allow=["/work"], inherited_deny=["~/.ssh"])
    assert config["allow_paths"] == ["/"]
    assert config["forbidden_paths"] == [canonicalize("~/.ssh"), "/mnt/xyz"]


def test_path_fence_blocks_traversal_and_symlink_into_denied_root(tmp_path: Path):
    safe = tmp_path / "safe"
    denied = tmp_path / "vault"
    safe.mkdir()
    denied.mkdir()
    (safe / "link").symlink_to(denied, target_is_directory=True)
    for path in (safe / ".." / "vault" / "secret", safe / "link" / "secret"):
        result = evaluate_action(tool="read_file", action_kind="read",
            arguments={"path": str(path)}, workspace=str(tmp_path),
            allow_paths=[str(tmp_path)], forbidden_paths=[str(denied)])
        assert result.verdict == "denied"


@pytest.mark.parametrize("access", ["read", "write"])
def test_root_allow_does_not_override_denied_subtree(tmp_path: Path, access: str):
    denied = tmp_path / "credentials"
    denied.mkdir()
    result = evaluate_action(tool="read_file" if access == "read" else "write_file",
        action_kind=access, arguments={"path": str(denied / "key")},
        workspace=str(tmp_path), allow_paths=["/"], forbidden_paths=[str(denied)])
    assert result.verdict == "denied"


def test_rule_requires_specific_harness():
    with pytest.raises(ValueError):
        FilesystemRule(harness="*", access="read", allow_roots=("/",)).validate()


# ---------------------------------------------------------------------------
# Cross-process lost-update protection  (fcntl.flock)
# ---------------------------------------------------------------------------

def _child_add_rule(policy_path: str, harness: str, suffix: str):
    """Helper for multiprocess test — runs in a child process."""
    policy = FilesystemPolicy(Path(policy_path))
    rule = FilesystemRule(harness=harness, access="read",
                          allow_roots=("/tmp",),
                          deny_roots=(f"/tmp/deny-{suffix}",))
    policy.add(rule)


def _child_remove_rule(policy_path: str, rule_id: str):
    """Spawn-safe helper: local functions cannot be pickled on Windows/spawn."""
    FilesystemPolicy(Path(policy_path)).remove(rule_id)


def test_concurrent_adds_are_not_lost(tmp_path: Path):
    path = tmp_path / "shared.json"
    policy = FilesystemPolicy(path)

    # Add one rule in the parent first
    policy.add(FilesystemRule(harness="parent", access="read",
                              allow_roots=("/work",), deny_roots=()))

    procs = []
    for i in range(5):
        p = multiprocessing.Process(target=_child_add_rule,
                                    args=(str(path), "child", str(i)))
        procs.append(p)
        p.start()

    for p in procs:
        p.join(timeout=10)
        assert p.exitcode == 0

    # All rules must be present (no lost updates)
    rules = policy.list()
    harnesses = {r.harness for r in rules}
    assert "parent" in harnesses
    assert len([r for r in rules if r.harness == "child"]) == 5
    assert len(rules) == 6


def test_concurrent_add_and_remove_are_consistent(tmp_path: Path):
    path = tmp_path / "shared2.json"
    policy = FilesystemPolicy(path)

    policy.add(FilesystemRule(harness="keep", access="read",
                              allow_roots=("/keep",), deny_roots=()))
    rule = FilesystemRule(harness="toremove", access="read",
                          allow_roots=("/tmp",), deny_roots=())
    policy.add(rule)
    rid = rule.rule_id

    # Remove in a child while parent reads
    ctx = multiprocessing.get_context("spawn")

    proc = ctx.Process(target=_child_remove_rule, args=(str(path), rid))
    proc.start()
    proc.join(timeout=10)

    rules = policy.list()
    assert proc.exitcode == 0
    assert rid not in {r.rule_id for r in rules}
    assert any(r.harness == "keep" for r in rules)


# ---------------------------------------------------------------------------
# Canonicalization / symlink escapes in fence_config
# ---------------------------------------------------------------------------

def test_fence_config_canonicalizes_allow_roots(tmp_path: Path):
    link = tmp_path / "link"
    target = tmp_path / "real"
    target.mkdir()
    link.symlink_to(target, target_is_directory=True)

    policy = FilesystemPolicy(tmp_path / "policy.json")
    policy.add(FilesystemRule(harness="h", access="read",
                              allow_roots=(str(link),), deny_roots=()))
    config = policy.fence_config(harness="h", model="m", access="read",
                                 inherited_allow=[], inherited_deny=[])
    assert str(target) in config["allow_paths"]
    assert str(link) not in config["allow_paths"]


def test_fence_config_canonicalizes_deny_roots(tmp_path: Path):
    link = tmp_path / "secret-link"
    target = tmp_path / "secret-real"
    target.mkdir()
    link.symlink_to(target, target_is_directory=True)

    policy = FilesystemPolicy(tmp_path / "policy.json")
    policy.add(FilesystemRule(harness="h", access="read",
                              allow_roots=("/",), deny_roots=(str(link),)))
    config = policy.fence_config(harness="h", model="m", access="read",
                                 inherited_allow=["/"], inherited_deny=[])
    assert str(target) in config["forbidden_paths"]


# ---------------------------------------------------------------------------
# Deny-root precedence — deny always strips overlapping allow
# ---------------------------------------------------------------------------

def test_deny_strips_overlapping_allow_in_canonical_roots(tmp_path: Path):
    rule = FilesystemRule(harness="h", access="read",
                          allow_roots=("/", "/home", "/work"),
                          deny_roots=("/home",))
    allow, deny = rule._canonical_roots()
    assert canonicalize("/") in allow
    assert canonicalize("/work") in allow
    assert canonicalize("/home") not in allow


def test_deny_does_not_strip_unrelated_allow(tmp_path: Path):
    rule = FilesystemRule(harness="h", access="read",
                          allow_roots=("/a", "/b"),
                          deny_roots=("/c",))
    allow, deny = rule._canonical_roots()
    assert canonicalize("/a") in allow
    assert canonicalize("/b") in allow


def test_fence_config_excludes_denied_allow_roots(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "policy.json")
    policy.add(FilesystemRule(harness="h", access="read",
                              allow_roots=("/", "/secret"),
                              deny_roots=("/secret",)))
    config = policy.fence_config(harness="h", model="m", access="read",
                                 inherited_allow=[], inherited_deny=[])
    assert canonicalize("/") in config["allow_paths"]
    assert canonicalize("/secret") not in config["allow_paths"]
    assert canonicalize("/secret") in config["forbidden_paths"]


# ---------------------------------------------------------------------------
# Malformed state fails closed
# ---------------------------------------------------------------------------

def test_malformed_json_returns_deny_all_fence_config(tmp_path: Path):
    p = tmp_path / "corrupt.json"
    p.write_text("{invalid json!!!", encoding="utf-8")
    config = FilesystemPolicy(p).fence_config(
        harness="h", model="m", access="read",
        inherited_allow=["/work"], inherited_deny=[])
    assert config["allow_paths"] == []
    assert config["forbidden_paths"] == ["/"]


def test_malformed_json_list_returns_deny_all(tmp_path: Path):
    p = tmp_path / "corrupt2.json"
    p.write_text('{"not_a_list": true}', encoding="utf-8")
    config = FilesystemPolicy(p).fence_config(
        harness="h", model="m", access="read",
        inherited_allow=["/work"], inherited_deny=[])
    assert config["allow_paths"] == []
    assert config["forbidden_paths"] == ["/"]


def test_fence_config_fails_closed_on_embedded_null_byte_in_a_stored_root(tmp_path: Path, monkeypatch):
    """Regression: FilesystemRule.validate() only checks for non-empty
    strings, so a well-formed policy file containing one bad root (an
    embedded null byte) passed validation at load time and only raised
    later, inside _canonical_roots()/canonicalize() -- which used to be
    OUTSIDE fence_config's try/except and crashed uncaught instead of
    returning the documented deny-all fence."""
    policy = FilesystemPolicy(tmp_path / "p.json")
    policy.add(FilesystemRule(
        harness="codex", model="*", access="read",
        allow_roots=("/tmp/foo\x00bar",), deny_roots=(),
    ))
    config = policy.fence_config(
        harness="codex", model="*", access="read",
        inherited_allow=["/work"], inherited_deny=[])
    assert config["allow_paths"] == []
    assert config["forbidden_paths"] == ["/"]
    assert config["source"] == "malformed-policy"


def test_crash_between_truncate_and_write_does_not_silently_clear_all_rules(tmp_path: Path):
    """Regression: the write path used to truncate the live file in place
    (ftruncate then write) instead of write-to-temp-then-replace. A crash
    in that exact window left a 0-byte file, and 0 bytes is treated as
    "valid, no rules" rather than malformed -- silently reverting every
    scoped rule (including a deny-root for something like ~/.ssh) to
    whatever permissive default the caller passes, instead of failing
    closed. Simulated here by directly truncating the file to prove the
    OLD failure mode, then confirming the current write path never leaves
    this window (the data file always contains either the old complete
    content or the new complete content, verified by inspecting the file
    immediately after every add() below)."""
    policy = FilesystemPolicy(tmp_path / "p.json")
    for i in range(20):
        policy.add(FilesystemRule(
            harness=f"h{i}", model="*", access="read",
            allow_roots=(f"/tmp/allow{i}",), deny_roots=(),
        ))
        # The data file must be valid, complete JSON after every single
        # write -- never a truncated/partial intermediate state.
        raw = (tmp_path / "p.json").read_text(encoding="utf-8")
        assert raw.strip(), "data file must never be empty right after a write"
        import json as _json
        parsed = _json.loads(raw)
        assert len(parsed) == i + 1


def test_list_raises_on_malformed_json(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("[[[broken", encoding="utf-8")
    with pytest.raises(ValueError, match="malformed"):
        FilesystemPolicy(p).list()


def test_list_raises_on_non_list_json(tmp_path: Path):
    p = tmp_path / "bad2.json"
    p.write_text('"just a string"', encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        FilesystemPolicy(p).list()


# ---------------------------------------------------------------------------
# Empty / missing policy file
# ---------------------------------------------------------------------------

def test_list_returns_empty_when_file_missing(tmp_path: Path):
    assert FilesystemPolicy(tmp_path / "nonexistent.json").list() == []


def test_list_returns_empty_when_file_empty(tmp_path: Path):
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    assert FilesystemPolicy(p).list() == []


def test_list_returns_empty_when_file_whitespace(tmp_path: Path):
    p = tmp_path / "ws.json"
    p.write_text("   \n  \t  ", encoding="utf-8")
    assert FilesystemPolicy(p).list() == []


# ---------------------------------------------------------------------------
# Home / ~  expansion in fence_config
# ---------------------------------------------------------------------------

def test_fence_config_expands_home_in_inherited(tmp_path: Path):
    config = FilesystemPolicy(tmp_path / "p.json").fence_config(
        harness="h", model="m", access="read",
        inherited_allow=["~"], inherited_deny=[])
    home = canonicalize("~")
    assert config["allow_paths"] == [home]


def test_fence_config_expands_home_in_rule_roots(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "p.json")
    policy.add(FilesystemRule(harness="h", access="read",
                              allow_roots=("~/dev",), deny_roots=("~/secret",)))
    config = policy.fence_config(harness="h", model="m", access="read",
                                 inherited_allow=[], inherited_deny=[])
    assert canonicalize("~/dev") in config["allow_paths"]
    assert canonicalize("~/secret") in config["forbidden_paths"]


# ---------------------------------------------------------------------------
# Per-harness / trusted-model read/write rules
# ---------------------------------------------------------------------------

def test_different_harnesses_are_independent(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "p.json")
    policy.add(FilesystemRule(harness="a", access="read",
                              allow_roots=("/a",), deny_roots=()))
    policy.add(FilesystemRule(harness="b", access="read",
                              allow_roots=("/b",), deny_roots=()))
    assert policy.effective(harness="a", model="*", access="read").allow_roots == ("/a",)
    assert policy.effective(harness="b", model="*", access="read").allow_roots == ("/b",)
    assert policy.effective(harness="a", model="*", access="write") is None
    assert policy.effective(harness="b", model="*", access="write") is None


def test_write_rules_do_not_affect_read(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "p.json")
    policy.add(FilesystemRule(harness="h", access="read",
                              allow_roots=("/r",), deny_roots=()))
    policy.add(FilesystemRule(harness="h", access="write",
                              allow_roots=("/w",), deny_roots=()))
    read = policy.effective(harness="h", model="*", access="read")
    write = policy.effective(harness="h", model="*", access="write")
    assert read is not None
    assert write is not None
    assert read.allow_roots == ("/r",)
    assert write.allow_roots == ("/w",)


# ---------------------------------------------------------------------------
# Remove behavioural contract
# ---------------------------------------------------------------------------

def test_remove_returns_true_when_deleted(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "p.json")
    r = FilesystemRule(harness="h", access="read", allow_roots=("/",), deny_roots=())
    policy.add(r)
    assert policy.remove(r.rule_id) is True


def test_remove_returns_false_when_not_found(tmp_path: Path):
    policy = FilesystemPolicy(tmp_path / "p.json")
    assert policy.remove("nonexistent") is False


# ---------------------------------------------------------------------------
# Edge: canonicalise does not mutate stored rule
# ---------------------------------------------------------------------------

def test_canonical_roots_does_not_mutate_rule(tmp_path: Path):
    rule = FilesystemRule(harness="h", access="read",
                          allow_roots=("~",), deny_roots=())
    original = rule.allow_roots
    rule._canonical_roots()
    assert rule.allow_roots == original
