"""Error-path tests for the stale-plugin check and receipt store failures.

These complete the productization error-path matrix:
- stale deployed plugin.yaml is detected by the doctor (mismatch with the
  shipped version), rather than passing as "enforcement verified";
- a failing receipt store fails closed in the guard runtime (a decision is
  never silently accepted when the receipt chain cannot be written).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from custodian.cli.main import main

_SHIPPED_YAML = (
    Path(__file__).resolve().parent.parent
    / "custodian" / "guards" / "hermes" / "plugin" / "plugin.yaml"
).read_text()


@pytest.fixture(autouse=True)
def no_real_hermes(monkeypatch, tmp_path):
    """Detection must not pick up the real host's Hermes install/PATH."""
    monkeypatch.setattr("custodian.cli.cmd_doctor.shutil.which", lambda name: None)
    monkeypatch.setattr("custodian.cli.cmd_doctor.Path.home", lambda: tmp_path)
    monkeypatch.delenv("HERMES_HOME", raising=False)


def _hermes_env(monkeypatch, tmp_path, talaria_policy: bool = True) -> Path:
    """Build the standard mocked Hermes environment; return plugin dir.

    Also activates the hermes guard in the gate (the runtime refuses to
    construct when the gate is off), and points the gate at the test's
    tmp_path state dir so the test can mutate it freely."""
    real_find_spec = __import__("importlib").util.find_spec
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.importlib.util.find_spec",
        lambda name: object() if name == "talaria" else real_find_spec(name),
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state_dir))
    from custodian.guards.gate import enable as _gate_enable
    _gate_enable(str(state_dir), "hermes")
    monkeypatch.setenv("TALARIA_HOME", str(tmp_path / "talaria"))
    hermes = tmp_path / "hermes"
    (hermes / "plugins" / "talaria-guard").mkdir(parents=True)
    (hermes / "plugins" / "talaria-guard" / "plugin.yaml").write_text("name: guard\n")
    (hermes / "plugins" / "custodian-hermes-guard").mkdir(parents=True)
    (talaria := tmp_path / "talaria").mkdir(exist_ok=True)
    if talaria_policy:
        (talaria / "policy.yaml").write_text("{}\n")
    monkeypatch.setenv("HERMES_HOME", str(hermes))
    return hermes / "plugins" / "custodian-hermes-guard"


def test_stale_plugin_yaml_fails_enforcement_check(monkeypatch, tmp_path, capsys):
    """A deployed plugin.yaml that differs from the shipped version fails the
    enforcement check with a clear 'rerun setup' instruction."""
    plugin_dir = _hermes_env(monkeypatch, tmp_path)
    (plugin_dir / "plugin.yaml").write_text(
        "name: custodian-hermes-guard\nversion: \"9.9.9\"\n"
    )

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "differs from the shipped version" in out
    assert "custodian setup --profile hermes" in out


def test_matching_plugin_yaml_passes_enforcement_check(monkeypatch, tmp_path, capsys):
    """The identical shipped plugin.yaml passes the enforcement check."""
    plugin_dir = _hermes_env(monkeypatch, tmp_path)
    (plugin_dir / "plugin.yaml").write_text(_SHIPPED_YAML)

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Ready" in out


def test_doctor_ready_with_both_plugins_enabled(monkeypatch, tmp_path, capsys):
    """Full happy path: both plugins enabled via `hermes plugins list`."""
    plugin_dir = _hermes_env(monkeypatch, tmp_path)
    (plugin_dir / "plugin.yaml").write_text(_SHIPPED_YAML)
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.shutil.which",
        lambda name: "/usr/bin/hermes" if name == "hermes" else None,
    )
    monkeypatch.setattr(
        "custodian.cli.cmd_doctor.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0,
            "enabled user 0.1 talaria-guard\n"
            "enabled user 0.1 custodian-hermes-guard\n",
            "",
        ),
    )

    rc = main(["doctor", "--profile", "hermes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Ready" in out


def _enable_hermes_in_tmp(monkeypatch, tmp_path):
    """Enable the hermes guard in tmp_path and point CUSTODIAN_STATE_DIR at it.

    The hermes runtime refuses to construct when the gate is off, so any
    test that builds a HermesGuardRuntime() needs this helper."""
    state_dir = tmp_path / "gate-state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CUSTODIAN_STATE_DIR", str(state_dir))
    from custodian.guards.gate import enable as _gate_enable
    _gate_enable(str(state_dir), "hermes")


def test_consume_failure_fails_closed(monkeypatch, tmp_path):
    """If consume() cannot write its claim marker (e.g. read-only approval
    store), wait_for_approval must resolve to a denied decision, never an
    approval that silently leaked through."""
    _enable_hermes_in_tmp(monkeypatch, tmp_path)
    from custodian.hermes_guard.runtime import HermesGuardRuntime
    from custodian.codex_guard.approvals import ApprovalStore

    runtime = HermesGuardRuntime()
    store = ApprovalStore(runtime._state_dir)

    digest = "a" * 64
    rec = store.request(
        digest=digest, requester="hermes:test", ttl_seconds=60, harness="hermes"
    )
    store.approve(rec.approval_id, approved_by="operator")

    def _boom(*a, **kw):
        raise OSError("read-only approval store")

    monkeypatch.setattr(
        "custodian.hermes_guard.runtime.os.open", _boom
    )

    decision = runtime.wait_for_approval(
        tool_name="write_file",
        args={"path": str(tmp_path / "evil.md"), "content": "x"},
        approval_id=rec.approval_id,
        requester="hermes:test",
        timeout_seconds=0.5,
    )
    assert decision.verdict == "denied"
    # The exact reason depends on which fail-closed path the runtime
    # takes: a store failure during get() reports "store failure",
    # a failure during the re-evaluation that attempts consume() reports
    # "guard evaluation failed closed". Both are correct fail-closed
    # behavior; the assertion is that the verdict is denied.
    assert (
        "store failure" in decision.reason
        or "ApprovalError" in decision.reason
        or "failing closed" in decision.reason
        or "guard evaluation failed" in decision.reason
    )


def test_brand_neutrality_no_talaria_in_user_facing_strings():
    """The OSS package must not surface 'Talaria' in any *user-facing*
    string. The legacy env-var name TALARIA_APPROVAL_WAIT_SECONDS is
    intentionally retained as a compatibility shim and is allowed in
    the *code* that implements the shim, but never in any message a
    model or operator might see.
    """
    import custodian.hermes_guard.contract as contract_mod
    import custodian.hermes_guard.plugin as plugin_mod
    import custodian.hermes_guard.runtime as runtime_mod

    for mod, name in [
        (contract_mod, "contract"),
        (plugin_mod, "plugin"),
        (runtime_mod, "runtime"),
    ]:
        if not (hasattr(mod, "__file__") and mod.__file__):
            continue
        # Strip out docstring regions before checking for "talaria" -- any
        # user-facing brand leakage must be a *code* occurrence, not a
        # comment explaining the rename history.
        text = open(mod.__file__).read()
        # Walk the file and drop lines that are inside any triple-quoted
        # block ("..." or '...'). Good enough for these small modules.
        in_doc = False
        quote_chars = ('"""', "'''")
        cleaned: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if in_doc:
                cleaned.append("")
                if any(q in stripped for q in quote_chars):
                    in_doc = False
                continue
            if any(stripped.startswith(q) for q in quote_chars) and any(
                q in stripped[len(q):] for q in quote_chars
            ):
                # Single-line docstring -- skip it entirely.
                cleaned.append("")
                continue
            if any(stripped.startswith(q) for q in quote_chars):
                in_doc = True
                cleaned.append("")
                continue
            cleaned.append(line)
        for line in cleaned:
            if "TALARIA_APPROVAL_WAIT_SECONDS" in line:
                # Only the os.environ.get compat shim may reference it.
                assert "os.environ.get" in line, (
                    f"{name}.py mentions TALARIA_APPROVAL_WAIT_SECONDS "
                    f"outside an os.environ.get shim: {line!r}"
                )
                continue
            if "talaria" in line.lower():
                # Any remaining mention is brand leakage.
                raise AssertionError(
                    f"{name}.py: code line mentions 'talaria': {line!r}"
                )

    # The brand-neutral env var is the primary, not the legacy one.
    import os
    os.environ.pop("CUSTODIAN_APPROVAL_WAIT_SECONDS", None)
    os.environ.pop("TALARIA_APPROVAL_WAIT_SECONDS", None)
    os.environ["CUSTODIAN_APPROVAL_WAIT_SECONDS"] = "77"
    try:
        assert contract_mod.approval_wait_seconds() == 77
    finally:
        os.environ.pop("CUSTODIAN_APPROVAL_WAIT_SECONDS", None)
    # Legacy env var still honored as a shim.
    os.environ["TALARIA_APPROVAL_WAIT_SECONDS"] = "42"
    try:
        assert contract_mod.approval_wait_seconds() == 42
    finally:
        os.environ.pop("TALARIA_APPROVAL_WAIT_SECONDS", None)


def test_consumed_approval_replay_fast_denies(monkeypatch, tmp_path):
    """A consumed approval must be denied immediately, not hung for the
    full wait window. consume() atomically sets status='consumed' and
    stamps consumed_at, so a replayed id never matches the 'approved'
    branch; without the explicit consumed-status check it would silently
    poll until the timeout.
    """
    _enable_hermes_in_tmp(monkeypatch, tmp_path)
    from custodian.hermes_guard.runtime import HermesGuardRuntime
    from custodian.codex_guard.approvals import ApprovalStore

    runtime = HermesGuardRuntime()
    store = ApprovalStore(runtime._state_dir)

    digest = "c" * 64
    rec = store.request(
        digest=digest, requester="hermes:test", ttl_seconds=60, harness="hermes"
    )
    store.approve(rec.approval_id, approved_by="operator")
    # Consume via the same path the engine does, so status flips to
    # 'consumed' and consumed_at is set.
    from custodian.codex_guard.approvals import action_digest as _ad
    store.consume(rec.approval_id, digest=digest, requester="hermes:test")

    # Now a replay with a very short timeout must return quickly with
    # the fast-deny reason, not the timeout reason.
    import time as _time
    t0 = _time.monotonic()
    decision = runtime.wait_for_approval(
        tool_name="write_file",
        args={"path": str(tmp_path / "x.md")},
        approval_id=rec.approval_id,
        requester="hermes:test",
        timeout_seconds=30.0,
    )
    elapsed = _time.monotonic() - t0
    assert decision.verdict == "denied"
    assert "replay denied" in decision.reason or "already consumed" in decision.reason
    assert elapsed < 2.0, (
        f"replay should fast-deny, but it took {elapsed:.2f}s (polled for 30s)"
    )


def test_changed_action_after_approval_fails_closed(monkeypatch, tmp_path):
    """An approval minted for action A must not authorize action B.

    The runtime must re-run the shared engine with the *current* invocation
    (tool, args, workspace, requester, session) so the action digest is
    recomputed and matched against the record. A model that hands back a
    previously-approved id but changes the args/workspace/requester must
    be denied, not silently authorized.
    """
    _enable_hermes_in_tmp(monkeypatch, tmp_path)
    from custodian.hermes_guard.runtime import HermesGuardRuntime
    from custodian.codex_guard.approvals import ApprovalStore

    runtime = HermesGuardRuntime()
    store = ApprovalStore(runtime._state_dir)

    digest = "b" * 64
    rec = store.request(
        digest=digest, requester="hermes:test", ttl_seconds=60, harness="hermes"
    )
    store.approve(rec.approval_id, approved_by="operator")

    # Different action: changed file, different content, different requester.
    decision = runtime.wait_for_approval(
        tool_name="write_file",
        args={"path": "/etc/passwd", "content": "pwned"},
        approval_id=rec.approval_id,
        requester="hermes:different-session",  # different from "hermes:test"
        workspace=str(tmp_path),
        session_id="different-session",
        timeout_seconds=0.5,
    )
    assert decision.verdict == "denied", (
        f"changed action must fail closed, got: {decision}"
    )
    # And the record must NOT be consumed; replay should be possible.
    post = store.get(rec.approval_id)
    assert post.consumed_at is None, (
        "the original record must remain unconsumed so the operator can "
        "still revoke it / see that nothing authorized it"
    )
