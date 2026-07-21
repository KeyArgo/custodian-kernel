"""Tests for the delegated executor's decision-making core (ExecutorService)
and, at the bottom, a real socket end-to-end test proving the separation
actually holds."""
from pathlib import Path

import pytest

from custodian.executor.capability import CapabilityStore, action_digest
from custodian.executor.service import ExecutorService


def _make_skill(root: Path, name: str, band: str, cost_usd: float, script_body: str) -> None:
    d = root / name
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test\n"
        f"metadata:\n  custodian:\n    band: {band}\n    cost_usd: {cost_usd}\n"
        f"    configured: true\n---\n"
    )
    (d / "scripts" / "execute.py").write_text(script_body)


@pytest.fixture
def skills_root(tmp_path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    return root


def _service(skills_root: Path, tmp_path: Path) -> ExecutorService:
    return ExecutorService(skills_root, state_dir=tmp_path / "executor-state")


def test_l0_tool_executes_directly_no_capability_involved(skills_root, tmp_path):
    _make_skill(skills_root, "echo", "L0", 0.0,
               "import json; print(json.dumps({'ok': True, 'ran': True}))\n")
    service = _service(skills_root, tmp_path)

    result = service.handle({"tool": "echo", "args": {}, "requester": "r"})
    assert result["ok"] is True
    assert result["ran"] is True


def test_l2_tool_within_cap_executes_autonomously(skills_root, tmp_path, monkeypatch):
    _make_skill(skills_root, "small-charge", "L2", 0.0,
               "import json; print(json.dumps({'ok': True}))\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)  # no real ~/.custodian policy/state
    service = _service(skills_root, tmp_path)

    result = service.handle({"tool": "small-charge", "args": {"amount": 1.0}, "requester": "r"})
    assert result["ok"] is True


def test_l2_tool_over_cap_escalates_without_executing(skills_root, tmp_path, monkeypatch):
    _make_skill(skills_root, "big-charge", "L2", 0.0,
               "raise AssertionError('must not execute before approval')\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    service = _service(skills_root, tmp_path)

    result = service.handle({
        "tool": "big-charge", "args": {"amount": 999999.0}, "requester": "r",
    })
    assert result["ok"] is False
    assert result["verdict"] == "escalation_required"
    assert "capability_id" in result


def test_denied_verdict_creates_no_capability(skills_root, tmp_path, monkeypatch):
    """A hard denial (e.g. kill switch) has nothing for a human to approve
    -- no capability should be created for it."""
    from custodian.tools.registry import _state_dir
    _make_skill(skills_root, "denied-tool", "L2", 0.0,
               "raise AssertionError('must not execute')\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # _kernel_decide reads the kill switch from _state_dir(), which honors
    # CUSTODIAN_STATE_DIR -- the test suite's autouse fixture always sets
    # that, so it (not Path.home()) is where this must be written.
    _state_dir().mkdir(parents=True, exist_ok=True)
    (_state_dir() / "kill_switch.json").write_text('{"killed": true}')
    service = _service(skills_root, tmp_path)

    result = service.handle({"tool": "denied-tool", "args": {"amount": 1.0}, "requester": "r"})
    assert result["ok"] is False
    assert result["verdict"] == "denied"
    assert "capability_id" not in result


def test_approving_the_capability_and_resending_executes_exactly_once(skills_root, tmp_path, monkeypatch):
    # Written inside the skill's own directory, which is rw-bound in the
    # sandbox -- tmp_path itself is only reachable read-only.
    calls_file = skills_root / "big-charge" / "calls.txt"
    _make_skill(skills_root, "big-charge", "L2", 0.0, f"""
import json
with open({str(calls_file)!r}, "a") as f:
    f.write("ran\\n")
print(json.dumps({{"ok": True}}))
""")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    service = _service(skills_root, tmp_path)

    request = {"tool": "big-charge", "args": {"amount": 999999.0}, "requester": "r"}
    first = service.handle(request)
    assert first["verdict"] == "escalation_required"
    assert not calls_file.exists()

    service.capabilities.approve(first["capability_id"], approved_by="operator")

    second = service.handle(request)  # identical request, now approved
    assert second["ok"] is True
    assert calls_file.read_text().count("ran") == 1

    # A third, identical request must NOT reuse the already-consumed
    # capability -- it escalates again, fresh, rather than replaying.
    third = service.handle(request)
    assert third["ok"] is False
    assert third["verdict"] == "escalation_required"
    assert third["capability_id"] != first["capability_id"]
    assert calls_file.read_text().count("ran") == 1  # still exactly once


def test_long_requester_string_does_not_break_approve_and_resend(skills_root, tmp_path, monkeypatch):
    """Regression: service.handle() truncated the incoming requester to 256
    chars, but CapabilityStore.request() truncates to 128 internally when
    storing it. A requester string between 129-256 chars got stored
    shorter than the value later compared against in
    find_pending_by_digest()/consume() -- the approved capability could
    never be found/consumed again, so the resend silently issued a fresh
    escalation forever instead of executing the approved one."""
    calls_file = skills_root / "big-charge" / "calls.txt"
    _make_skill(skills_root, "big-charge", "L2", 0.0, f"""
import json
with open({str(calls_file)!r}, "a") as f:
    f.write("ran\\n")
print(json.dumps({{"ok": True}}))
""")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    service = _service(skills_root, tmp_path)

    long_requester = "session:" + "x" * 200  # 208 chars, between 128 and 256
    request = {"tool": "big-charge", "args": {"amount": 999999.0}, "requester": long_requester}
    first = service.handle(request)
    assert first["verdict"] == "escalation_required"

    service.capabilities.approve(first["capability_id"], approved_by="operator")

    second = service.handle(request)  # identical resend, now approved
    assert second["ok"] is True, f"resend did not find the approved capability: {second}"
    assert calls_file.read_text().count("ran") == 1


def test_approval_for_one_action_cannot_execute_a_different_action(skills_root, tmp_path, monkeypatch):
    """The core delegated-execution guarantee: an operator approving action
    A must not let action B (different args) execute."""
    calls_file = skills_root / "transfer" / "calls.txt"
    _make_skill(skills_root, "transfer", "L2", 0.0, f"""
import json
with open({str(calls_file)!r}, "a") as f:
    f.write("ran\\n")
print(json.dumps({{"ok": True}}))
""")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    service = _service(skills_root, tmp_path)

    legit = {"tool": "transfer", "args": {"amount": 999999.0}, "requester": "r"}
    fraud = {"tool": "transfer", "args": {"amount": 1_000_000.0}, "requester": "r"}

    escalated = service.handle(legit)
    service.capabilities.approve(escalated["capability_id"], approved_by="operator")

    # Attacker tries to execute a DIFFERENT amount using the approval meant
    # for `legit` by directly forging a consume() call against it.
    digest_fraud = action_digest(tool="transfer", args=fraud["args"], workspace="", requester="r")
    with pytest.raises(Exception):
        service.capabilities.consume(escalated["capability_id"], digest=digest_fraud, requester="r")
    assert not calls_file.exists()

    # The legitimate action still works via the normal resend path.
    result = service.handle(legit)
    assert result["ok"] is True
    assert calls_file.read_text().count("ran") == 1


def test_unconfigured_tool_returns_stub_without_any_capability(skills_root, tmp_path):
    d = skills_root / "needs-key"
    (d / "scripts").mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: needs-key\ndescription: test\n"
        "metadata:\n  custodian:\n    band: L2\n    configured: false\n---\n"
    )
    (d / "scripts" / "execute.py").write_text("raise AssertionError('must not run')\n")
    service = _service(skills_root, tmp_path)

    result = service.handle({"tool": "needs-key", "args": {}, "requester": "r"})
    assert result["ok"] is False
    assert result.get("stub") is True
    assert "capability_id" not in result


def test_unknown_tool_returns_a_structured_error(skills_root, tmp_path):
    service = _service(skills_root, tmp_path)
    result = service.handle({"tool": "does-not-exist", "args": {}, "requester": "r"})
    assert result["ok"] is False
    assert "not found" in result["error"]


# ── Real socket end-to-end: prove the client cannot execute anything itself ──

def test_client_module_has_no_execution_code():
    """Structural guarantee, not just a behavioral one: the client's own
    code contains no subprocess/exec/os.system call (an AST-level check --
    not a plain substring search, which would false-positive on this exact
    claim being described in the module's own docstring). An agent process
    that only ever imports this module cannot run a governed script under
    any circumstance, however compromised, without the executor's
    cooperation over the socket."""
    import ast
    import custodian.executor.client as client_mod

    tree = ast.parse(Path(client_mod.__file__).read_text())
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("system", "popen", "execv", "execve", "execvp", "spawnv"):
                pytest.fail(f"found a forbidden call: os.{node.func.attr}")

    assert "subprocess" not in imported_names
    assert "pty" not in imported_names


def test_end_to_end_over_a_real_unix_socket(skills_root, tmp_path, monkeypatch):
    import threading
    from custodian.executor.service import ExecutorServer
    from custodian.executor.client import ExecutorClient

    calls_file = skills_root / "echo" / "calls.txt"
    _make_skill(skills_root, "echo", "L0", 0.0,
               f"""
import json
with open({str(calls_file)!r}, "a") as f:
    f.write("ran\\n")
print(json.dumps({{"ok": True}}))
""")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    service = _service(skills_root, tmp_path)
    socket_path = tmp_path / "executor.sock"
    server = ExecutorServer(socket_path, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ExecutorClient(socket_path)
        result = client.propose("echo", {}, requester="session:abc")
        assert result["ok"] is True
        assert calls_file.read_text().count("ran") == 1
    finally:
        server.shutdown()
        server.server_close()


# ── CustodianTool.invoke()'s opt-in delegated mode ──────────────────────────

def test_invoke_delegates_to_the_executor_when_socket_env_var_is_set(skills_root, tmp_path, monkeypatch):
    """When CUSTODIAN_EXECUTOR_SOCKET is set, invoke() must not run the
    script itself at all -- it only ever talks to the socket."""
    import threading
    from custodian.executor.service import ExecutorServer
    from custodian.tools.registry import CustodianTool

    calls_file = skills_root / "echo" / "calls.txt"
    _make_skill(skills_root, "echo", "L0", 0.0, f"""
import json
with open({str(calls_file)!r}, "a") as f:
    f.write("ran\\n")
print(json.dumps({{"ok": True}}))
""")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    service = _service(skills_root, tmp_path)
    socket_path = tmp_path / "executor.sock"
    server = ExecutorServer(socket_path, service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("CUSTODIAN_EXECUTOR_SOCKET", str(socket_path))
    try:
        tool = service.registry.get("echo")
        result = tool.invoke(requester="session:xyz")
        assert result["ok"] is True
        assert calls_file.read_text().count("ran") == 1
    finally:
        server.shutdown()
        server.server_close()


def test_invoke_delegated_mode_returns_structured_error_when_executor_unreachable(tmp_path, monkeypatch):
    from custodian.tools.registry import CustodianTool

    monkeypatch.setenv("CUSTODIAN_EXECUTOR_SOCKET", str(tmp_path / "does-not-exist.sock"))
    script = tmp_path / "execute.py"
    script.write_text("raise AssertionError('must not run in-process while delegated')\n")
    tool = CustodianTool(name="whatever", description="", band="L0",
                         configured=True, execute_script=script)

    result = tool.invoke()
    assert result["ok"] is False
    assert "not reachable" in result["error"]
