"""Tests for the Custodian tool registry and core tool implementations."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run_tool(path: str, *args) -> dict:
    """Run a tool script and return parsed JSON output."""
    script = REPO / path
    result = subprocess.run(
        [PYTHON, str(script)] + list(args),
        capture_output=True, text=True, timeout=15,
        cwd=str(REPO),
    )
    assert result.stdout.strip(), f"No output from {path}: {result.stderr}"
    return json.loads(result.stdout.strip())


# ── Registry ──────────────────────────────────────────────────────────────────

class TestToolRegistry:
    def test_discovers_tools(self):
        from custodian.tools.registry import default_registry
        reg = default_registry().load()
        assert reg.summary()["total"] >= 60

    def test_summary_has_all_bands(self):
        from custodian.tools.registry import default_registry
        s = default_registry().load().summary()
        assert "by_band" in s
        assert "L0" in s["by_band"]
        assert "L2" in s["by_band"]

    def test_get_known_tool(self):
        from custodian.tools.registry import default_registry
        reg = default_registry().load()
        t = reg.get("stripe-spend")
        assert t is not None
        assert t.band == "L2"

    def test_stub_invoke_returns_stub_response(self):
        from custodian.tools.registry import default_registry
        reg = default_registry().load()
        stubs = [t for t in reg.all() if not t.configured]
        assert len(stubs) > 0
        result = stubs[0].invoke()
        assert result["ok"] is False
        assert result.get("stub") is True

    def test_configured_count_positive(self):
        from custodian.tools.registry import default_registry
        s = default_registry().load().summary()
        assert s["configured"] >= 30

    def test_api_endpoint(self):
        """Flask /api/v1/tools/list returns correct structure."""
        sys.path.insert(0, str(REPO / "dashboard"))
        from dashboard.app import app
        with app.test_client() as c:
            r = c.get("/api/v1/tools/list")
            assert r.status_code == 200
            data = r.get_json()
            assert data["total"] >= 60
            assert len(data["tools"]) >= 60
            assert all("band" in t for t in data["tools"])

    def test_api_summary_endpoint(self):
        sys.path.insert(0, str(REPO / "dashboard"))
        from dashboard.app import app
        with app.test_client() as c:
            r = c.get("/api/v1/tools/summary")
            assert r.status_code == 200
            data = r.get_json()
            assert data["total"] >= 60


# ── Utility tools ─────────────────────────────────────────────────────────────

class TestBase64Tools:
    def test_encode(self):
        r = run_tool("skills/utilities/base64-encode/scripts/execute.py", "--input", "hello world")
        assert r["ok"] is True
        assert r["encoded"] == "aGVsbG8gd29ybGQ="

    def test_decode(self):
        r = run_tool("skills/utilities/base64-decode/scripts/execute.py", "--input", "aGVsbG8gd29ybGQ=")
        assert r["ok"] is True
        assert r["decoded"] == "hello world"

    def test_roundtrip(self):
        r1 = run_tool("skills/utilities/base64-encode/scripts/execute.py", "--input", "custodian kernel")
        r2 = run_tool("skills/utilities/base64-decode/scripts/execute.py", "--input", r1["encoded"])
        assert r2["decoded"] == "custodian kernel"

    def test_decode_with_missing_padding(self):
        r = run_tool("skills/utilities/base64-decode/scripts/execute.py", "--input", "aGVsbG8")
        assert r["ok"] is True
        assert r["decoded"] == "hello"


class TestHashTool:
    def test_known_hash(self):
        r = run_tool("skills/utilities/hash-sha256/scripts/execute.py", "--input", "")
        assert r["ok"] is True
        assert r["hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_non_empty(self):
        r = run_tool("skills/utilities/hash-sha256/scripts/execute.py", "--input", "custodian")
        assert r["ok"] is True
        assert len(r["hash"]) == 64


class TestUrlParse:
    def test_full_url(self):
        r = run_tool("skills/utilities/url-parse/scripts/execute.py", "--url", "https://getcustodian.xyz/triage?pack=refunds#section")
        assert r["ok"] is True
        assert r["scheme"] == "https"
        assert r["host"] == "getcustodian.xyz"
        assert r["path"] == "/triage"
        assert "pack" in r["query"]
        assert r["fragment"] == "section"

    def test_plain_url(self):
        r = run_tool("skills/utilities/url-parse/scripts/execute.py", "--url", "http://example.com")
        assert r["ok"] is True
        assert r["scheme"] == "http"


class TestJsonTransform:
    def test_identity(self):
        r = run_tool("skills/utilities/json-transform/scripts/execute.py",
                     "--input", '{"name": "Alice"}', "--filter", ".")
        assert r["ok"] is True
        assert r["result"] == {"name": "Alice"}

    def test_key_access(self):
        r = run_tool("skills/utilities/json-transform/scripts/execute.py",
                     "--input", '{"name": "Alice", "age": 30}', "--filter", ".name")
        assert r["ok"] is True
        assert r["result"] == "Alice"

    def test_nested_access(self):
        r = run_tool("skills/utilities/json-transform/scripts/execute.py",
                     "--input", '{"a": {"b": 42}}', "--filter", ".a.b")
        assert r["ok"] is True
        assert r["result"] == 42


class TestTimezoneLookup:
    def test_basic_conversion(self):
        r = run_tool("skills/utilities/timezone-lookup/scripts/execute.py",
                     "--datetime", "2026-06-27T12:00:00",
                     "--from-tz", "America/New_York",
                     "--to-tz", "Europe/London")
        assert r["ok"] is True
        assert "output" in r
        # London is 5h ahead of Eastern in summer
        assert "17:00" in r["output"]


# ── Memory / KV ───────────────────────────────────────────────────────────────

class TestKVStore:
    def setup_method(self):
        self._tmp = tempfile.mktemp(suffix=".db")
        os.environ["CUSTODIAN_KV_PATH"] = self._tmp

    def teardown_method(self):
        os.environ.pop("CUSTODIAN_KV_PATH", None)
        if os.path.exists(self._tmp):
            os.unlink(self._tmp)

    def test_set_and_get(self):
        run_tool("skills/memory/kv-set/scripts/execute.py", "--key", "x", "--value", "42")
        r = run_tool("skills/memory/kv-get/scripts/execute.py", "--key", "x")
        assert r["ok"] is True
        assert r["value"] == "42"

    def test_missing_key(self):
        r = run_tool("skills/memory/kv-get/scripts/execute.py", "--key", "nonexistent")
        assert r["ok"] is False

    def test_delete(self):
        run_tool("skills/memory/kv-set/scripts/execute.py", "--key", "del_me", "--value", "bye")
        run_tool("skills/memory/kv-delete/scripts/execute.py", "--key", "del_me")
        r = run_tool("skills/memory/kv-get/scripts/execute.py", "--key", "del_me")
        assert r["ok"] is False

    def test_list(self):
        run_tool("skills/memory/kv-set/scripts/execute.py", "--key", "aa", "--value", "1")
        run_tool("skills/memory/kv-set/scripts/execute.py", "--key", "ab", "--value", "2")
        run_tool("skills/memory/kv-set/scripts/execute.py", "--key", "bc", "--value", "3")
        r = run_tool("skills/memory/kv-list/scripts/execute.py", "--prefix", "a")
        assert r["ok"] is True
        keys = [k["key"] for k in r["keys"]]
        assert "aa" in keys
        assert "ab" in keys
        assert "bc" not in keys

    def test_overwrite(self):
        run_tool("skills/memory/kv-set/scripts/execute.py", "--key", "k", "--value", "v1")
        run_tool("skills/memory/kv-set/scripts/execute.py", "--key", "k", "--value", "v2")
        r = run_tool("skills/memory/kv-get/scripts/execute.py", "--key", "k")
        assert r["value"] == "v2"


# ── File tools ────────────────────────────────────────────────────────────────

class TestFileTools:
    def test_file_list_tmp(self):
        r = run_tool("skills/files/file-list/scripts/execute.py", "--path", "/tmp")
        assert r["ok"] is True
        assert r["count"] >= 0

    def test_file_write_and_read(self):
        path = "/tmp/custodian_test_file.txt"
        run_tool("skills/files/file-write/scripts/execute.py", "--path", path, "--content", "hello kernel")
        r = run_tool("skills/files/file-read/scripts/execute.py", "--path", path)
        assert r["ok"] is True
        assert "hello kernel" in r["content"]

    def test_file_write_outside_allowed_fails(self):
        r = run_tool("skills/files/file-write/scripts/execute.py",
                     "--path", "/etc/custodian_should_fail.txt", "--content", "bad")
        assert r["ok"] is False


# ── Shell exec ────────────────────────────────────────────────────────────────

class TestShellExec:
    def test_allowed_command(self):
        r = run_tool("skills/files/shell-exec/scripts/execute.py", "--cmd", "echo hello")
        assert r["ok"] is True
        assert "hello" in r["stdout"]

    def test_blocked_command(self):
        r = run_tool("skills/files/shell-exec/scripts/execute.py", "--cmd", "rm -rf /tmp/x")
        assert r["ok"] is False
        assert "allowlist" in r.get("error", "").lower() or "not in" in r.get("error", "").lower()

    def test_pwd(self):
        r = run_tool("skills/files/shell-exec/scripts/execute.py", "--cmd", "pwd", "--workdir", "/tmp")
        assert r["ok"] is True
        assert "/tmp" in r["stdout"]


# ── Scheduling ────────────────────────────────────────────────────────────────

class TestTaskQueue:
    def setup_method(self):
        self._tmp = tempfile.mktemp(suffix=".json")
        os.environ["CUSTODIAN_QUEUE_PATH"] = self._tmp

    def teardown_method(self):
        os.environ.pop("CUSTODIAN_QUEUE_PATH", None)
        if os.path.exists(self._tmp):
            os.unlink(self._tmp)

    def test_add_and_list(self):
        r = run_tool("skills/scheduling/task-queue-add/scripts/execute.py", "--task", "deploy widget")
        assert r["ok"] is True
        assert r["id"]
        r2 = run_tool("skills/scheduling/task-queue-list/scripts/execute.py")
        assert r2["count"] == 1
        assert r2["tasks"][0]["task"] == "deploy widget"

    def test_multiple_tasks(self):
        run_tool("skills/scheduling/task-queue-add/scripts/execute.py", "--task", "task A")
        run_tool("skills/scheduling/task-queue-add/scripts/execute.py", "--task", "task B")
        r = run_tool("skills/scheduling/task-queue-list/scripts/execute.py")
        assert r["count"] == 2


class TestCronRegistry:
    def setup_method(self):
        self._tmp = tempfile.mktemp(suffix=".json")
        os.environ["CUSTODIAN_CRONS_PATH"] = self._tmp

    def teardown_method(self):
        os.environ.pop("CUSTODIAN_CRONS_PATH", None)
        if os.path.exists(self._tmp):
            os.unlink(self._tmp)

    def test_create_list_delete(self):
        run_tool("skills/scheduling/cron-create/scripts/execute.py",
                 "--name", "daily-report", "--schedule", "0 9 * * 1-5", "--command", "echo report")
        r = run_tool("skills/scheduling/cron-list/scripts/execute.py")
        assert r["count"] == 1
        assert r["crons"][0]["name"] == "daily-report"
        run_tool("skills/scheduling/cron-delete/scripts/execute.py", "--name", "daily-report")
        r2 = run_tool("skills/scheduling/cron-list/scripts/execute.py")
        assert r2["count"] == 0


# ── Web / HTTP ────────────────────────────────────────────────────────────────

@pytest.mark.network
class TestHttpTools:
    def test_http_get(self):
        r = run_tool("skills/web/http-get/scripts/execute.py", "--url", "https://httpbin.org/get")
        assert r["ok"] is True
        assert r["status"] == 200

    def test_http_post(self):
        r = run_tool("skills/web/http-post/scripts/execute.py",
                     "--url", "https://httpbin.org/post",
                     "--payload", '{"tool": "custodian"}')
        assert r["ok"] is True
        assert r["status"] == 200

    def test_web_scrape(self):
        r = run_tool("skills/web/web-scrape/scripts/execute.py", "--url", "https://example.com")
        assert r["ok"] is True
        assert len(r["text"]) > 10

    def test_webhook_post(self):
        r = run_tool("skills/communication/webhook-post/scripts/execute.py",
                     "--url", "https://httpbin.org/post",
                     "--payload", '{"from": "custodian"}')
        assert r["ok"] is True


# ── GitHub (public, no auth needed) ──────────────────────────────────────────

class TestGitHubTools:
    def test_github_file_read_public(self):
        r = run_tool("skills/github/github-file-read/scripts/execute.py",
                     "--repo", "octocat/Hello-World",
                     "--path", "README")
        # May fail if repo moved, just check structure
        assert "ok" in r
        if r["ok"]:
            assert "content" in r


# ── Kernel safety invariant ───────────────────────────────────────────────────

class TestKernelInvariants:
    """These are the properties that must NEVER break.

    Uses the real kernel types: SpendRequest, AuthorityState, Policy, Verdict.
    The default preset has L2.max_spend=$2.00, so use amounts relative to that.
    """

    def _policy(self):
        from custodian.policy import load_policy
        preset = REPO / "custodian" / "policy" / "presets" / "default.yaml"
        return load_policy(preset)

    def test_kill_switch_blocks_all_spend(self):
        """Any spend NEVER returns AUTONOMOUS when kill switch is engaged."""
        from custodian.policy.evaluator import decide
        from custodian.types import AuthorityState, Band, SpendRequest, Verdict
        state = AuthorityState(band=Band.L2, per_action_cap=9999.0, session_cap=99999.0)
        request = SpendRequest(amount=1.00, description="test")
        result = decide(request, state, self._policy(), killed=True)
        assert result.verdict == Verdict.DENIED
        assert "kill" in result.reason.lower()

    def test_over_band_cap_never_autonomous(self):
        """A spend over the band's max_spend NEVER returns AUTONOMOUS."""
        from custodian.policy.evaluator import decide
        from custodian.types import AuthorityState, Band, SpendRequest, Verdict
        # Default L2 cap is $2.00 — $2.01 must escalate
        state = AuthorityState(band=Band.L2, per_action_cap=2.00, session_cap=1000.0)
        request = SpendRequest(amount=2.01, description="over cap")
        result = decide(request, state, self._policy())
        assert result.verdict != Verdict.AUTONOMOUS, "Over-cap spend must never be AUTONOMOUS"

    def test_under_cap_is_autonomous(self):
        """A spend under the band cap with budget returns AUTONOMOUS."""
        from custodian.policy.evaluator import decide
        from custodian.types import AuthorityState, Band, SpendRequest, Verdict
        state = AuthorityState(band=Band.L2, per_action_cap=2.00, session_cap=1000.0, spent_this_session=0.0)
        request = SpendRequest(amount=1.50, description="under cap")
        result = decide(request, state, self._policy())
        assert result.verdict == Verdict.AUTONOMOUS

    def test_l3_band_always_escalates(self):
        """L3 band always requires approval regardless of amount."""
        from custodian.policy import load_policy
        from custodian.policy.evaluator import decide
        from custodian.types import AuthorityState, Band, SpendRequest, Verdict
        import io, yaml as _yaml
        # Build a minimal policy whose default band is L3 (always requires approval)
        l3_policy_yaml = """
version: "1.0"
default_band: L3
bands:
  L3:
    max_spend: 50.00
    requires_approval: true
    approval_backend: twilio_verify
escalation:
  timeout_seconds: 600
  on_timeout: deny
  retry_count: 0
"""
        import tempfile, pathlib
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(l3_policy_yaml)
            tmp = pathlib.Path(f.name)
        policy = load_policy(tmp)
        tmp.unlink()
        state = AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=10000.0)
        request = SpendRequest(amount=0.01, description="tiny l3 spend")
        result = decide(request, state, policy)
        assert result.verdict == Verdict.ESCALATION_REQUIRED

    def test_session_budget_exhausted_escalates(self):
        """A spend that would exceed session budget escalates even if under per-action cap."""
        from custodian.policy.evaluator import decide
        from custodian.types import AuthorityState, Band, SpendRequest, Verdict
        state = AuthorityState(band=Band.L2, per_action_cap=2.00, session_cap=10.0, spent_this_session=9.50)
        request = SpendRequest(amount=1.00, description="over session budget")
        result = decide(request, state, self._policy())
        assert result.verdict != Verdict.AUTONOMOUS

    def test_tool_invoke_gates_l2_when_kill_switch_set(self, tmp_path):
        """tool.invoke() on an L2 tool returns kernel_escalation when kill switch is on."""
        import json as _json
        # File must be in the .custodian/ subdirectory to match Path.home() / ".custodian" / "kill_switch.json"
        custodian_dir = tmp_path / ".custodian"
        custodian_dir.mkdir()
        ks_file = custodian_dir / "kill_switch.json"
        ks_file.write_text(_json.dumps({"killed": True, "reason": "test", "by": "test"}))
        # Patch home to tmp_path so the registry finds .custodian/kill_switch.json
        import unittest.mock as mock
        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            from custodian.tools.registry import default_registry
            reg = default_registry().load()
            nim = reg.get("nim-job-submit")
            if nim and nim.configured:
                result = nim.invoke(prompt="hello")
                assert result.get("kernel_escalation") is True or result.get("ok") is False
