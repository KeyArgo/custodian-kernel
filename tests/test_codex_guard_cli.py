"""Tests for custodian.codex_guard.cli -- MCP registration, doctor, setup."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from custodian.codex_guard.cli import (
    _diagnose_stale_registration,
    _ensure_mcp_json,
    _mcp_command,
    _verify_mcp_handshake,
    main as cli_main,
)


# ------------------------------------------------------------------
# _mcp_command
# ------------------------------------------------------------------

class TestMcpCommand:
    def test_uses_absolute_interpreter(self):
        cmd = _mcp_command()
        assert cmd[0] == sys.executable
        assert cmd[1:] == ["-m", "custodian.codex_guard.mcp_server"]

    def test_survives_path_differences(self):
        cmd = _mcp_command()
        assert "/" in cmd[0]
        assert cmd[0] != "python3"


# ------------------------------------------------------------------
# _verify_mcp_handshake
# ------------------------------------------------------------------

class TestVerifyMcpHandshake:
    def test_returns_false_for_nonexistent_command(self):
        assert _verify_mcp_handshake([sys.executable, "-c", "raise SystemExit(1)"]) is False

    def test_returns_false_for_timeout(self):
        assert _verify_mcp_handshake([sys.executable, "-c", "import time; time.sleep(60)"]) is False

    def test_handshake_with_working_mcp_server(self):
        code = (
            "import sys, json;"
            "raw = sys.stdin.readline();"
            "req = json.loads(raw);"
            'resp = {"jsonrpc":"2.0","id":req["id"],'
            '"result":{"protocolVersion":"2025-06-18","capabilities":{},'
            '"serverInfo":{"name":"test","version":"0.0.0"}}};'
            "sys.stdout.write(json.dumps(resp)+'\\n');"
            "sys.stdout.flush()"
        )
        assert _verify_mcp_handshake([sys.executable, "-c", code]) is True

    def test_handshake_fails_on_wrong_id(self):
        code = (
            "import sys, json;"
            'resp = {"jsonrpc":"2.0","id":99,"result":{}};'
            "sys.stdout.write(json.dumps(resp)+'\\n');"
            "sys.stdout.flush()"
        )
        assert _verify_mcp_handshake([sys.executable, "-c", code]) is False


# ------------------------------------------------------------------
# _diagnose_stale_registration
# ------------------------------------------------------------------

class TestDiagnoseStaleRegistration:
    def test_reports_not_stale_when_command_matches(self, tmp_path):
        mcp = tmp_path / "mcp.json"
        payload = {
            "mcpServers": {
                "custodian-codex-guard": {
                    "command": sys.executable,
                    "args": ["-m", "custodian.codex_guard.mcp_server"],
                }
            }
        }
        mcp.write_text(json.dumps(payload))
        is_stale, detail = _diagnose_stale_registration(mcp)
        assert not is_stale

    def test_reports_stale_when_command_differs(self, tmp_path):
        mcp = tmp_path / "mcp.json"
        payload = {
            "mcpServers": {
                "custodian-codex-guard": {
                    "command": "python3",
                    "args": ["-m", "custodian.codex_guard.mcp_server"],
                }
            }
        }
        mcp.write_text(json.dumps(payload))
        is_stale, detail = _diagnose_stale_registration(mcp)
        assert is_stale
        assert "registered: python3" in detail

    def test_reports_stale_when_args_differ(self, tmp_path):
        mcp = tmp_path / "mcp.json"
        payload = {
            "mcpServers": {
                "custodian-codex-guard": {
                    "command": sys.executable,
                    "args": ["-m", "custodian.codex_guard.mcp_server", "--extra"],
                }
            }
        }
        mcp.write_text(json.dumps(payload))
        is_stale, detail = _diagnose_stale_registration(mcp)
        assert is_stale
        assert "--extra" in detail

    def test_returns_not_stale_for_missing_file(self, tmp_path):
        missing = tmp_path / "nonexistent.json"
        is_stale, detail = _diagnose_stale_registration(missing)
        assert not is_stale
        assert "no mcp.json found" in detail

    def test_returns_not_stale_for_corrupt_json(self, tmp_path):
        corrupt = tmp_path / "mcp.json"
        corrupt.write_text("not json")
        is_stale, detail = _diagnose_stale_registration(corrupt)
        assert not is_stale
        assert "parse error" in detail


# ------------------------------------------------------------------
# _ensure_mcp_json
# ------------------------------------------------------------------

class TestEnsureMcpJson:
    def test_writes_correct_command(self, tmp_path):
        mcp = tmp_path / "sub" / "mcp.json"
        with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True):
            result = _ensure_mcp_json(mcp)

        assert mcp.exists()
        data = json.loads(mcp.read_text())
        server = data["mcpServers"]["custodian-codex-guard"]
        assert server["command"] == sys.executable
        assert server["args"] == ["-m", "custodian.codex_guard.mcp_server"]
        assert result is True

    def test_creates_parent_directory(self, tmp_path):
        mcp = tmp_path / "a" / "b" / "mcp.json"
        with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True):
            _ensure_mcp_json(mcp)
        assert mcp.parent.exists()

    def test_idempotent_when_unchanged(self, tmp_path):
        mcp = tmp_path / "mcp.json"
        with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True):
            _ensure_mcp_json(mcp)
            first_stat = mcp.stat()
            _ensure_mcp_json(mcp)
        second_stat = mcp.stat()
        assert first_stat.st_mtime <= second_stat.st_mtime
        data = json.loads(mcp.read_text())
        assert data["mcpServers"]["custodian-codex-guard"]["command"] == sys.executable

    def test_replaces_stale_command(self, tmp_path):
        mcp = tmp_path / "mcp.json"
        stale = {
            "mcpServers": {
                "custodian-codex-guard": {
                    "command": "python3",
                    "args": [],
                }
            }
        }
        mcp.write_text(json.dumps(stale))
        with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True):
            _ensure_mcp_json(mcp)
        data = json.loads(mcp.read_text())
        assert data["mcpServers"]["custodian-codex-guard"]["command"] == sys.executable

    def test_handshake_failure_returns_false(self, tmp_path):
        mcp = tmp_path / "mcp.json"
        with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=False):
            result = _ensure_mcp_json(mcp)
        assert result is False
        assert mcp.exists()

    def test_handles_corrupt_existing_file(self, tmp_path):
        mcp = tmp_path / "mcp.json"
        mcp.write_text("{corrupt")
        with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True):
            result = _ensure_mcp_json(mcp)
        assert result is True
        data = json.loads(mcp.read_text())
        assert data["mcpServers"]["custodian-codex-guard"]["command"] == sys.executable


# ------------------------------------------------------------------
# CLI integration: setup --dry-run
# ------------------------------------------------------------------

class TestCliSetupDryRun:
    def test_dry_run_prints_intent(self, capsys):
        rc = cli_main(["setup", "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "would run:" in out
        assert "codex plugin marketplace add" in out
        assert "codex plugin add" in out

    def test_dry_run_does_not_call_subprocess(self, capsys):
        with (
            patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True),
            patch("custodian.codex_guard.cli.subprocess.run") as mock_run,
        ):
            rc = cli_main(["setup", "--dry-run"])
        assert rc == 0
        mock_run.assert_not_called()

    def test_dry_run_does_not_write_mcp_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with patch("custodian.codex_guard.cli._repo_root", return_value=tmp_path):
            assert cli_main(["setup", "--dry-run"]) == 0
        assert not (tmp_path / "mcp.json").exists()
        assert not (tmp_path / "plugins" / "custodian-codex-guard" / ".mcp.json").exists()


def test_ensure_mcp_json_preserves_other_servers(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "other"}}}))
    with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True):
        assert _ensure_mcp_json(path)
    assert "other" in json.loads(path.read_text())["mcpServers"]

    def test_dry_run_shows_mcp_command(self, capsys):
        rc = cli_main(["setup", "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert sys.executable in out
        assert "custodian.codex_guard.mcp_server" in out


# ------------------------------------------------------------------
# CLI integration: doctor
# ------------------------------------------------------------------

class TestCliDoctor:
    def test_doctor_python_version(self, capsys):
        rc = cli_main(["doctor"])
        out = capsys.readouterr().out
        assert "python" in out
        assert rc in (0, 1)

    def test_doctor_cwd_freshness_when_no_mcp_json(self, capsys):
        rc = cli_main(["doctor"])
        out = capsys.readouterr().out
        assert rc in (0, 1)

    def test_doctor_plugin_mcp_detected(self, capsys, tmp_path, monkeypatch):
        plugin_dir = tmp_path / "plugins" / "custodian-codex-guard"
        plugin_dir.mkdir(parents=True)
        mcp = plugin_dir / ".mcp.json"
        payload = {
            "mcpServers": {
                "custodian-codex-guard": {
                    "command": sys.executable,
                    "args": ["-m", "custodian.codex_guard.mcp_server"],
                }
            }
        }
        mcp.write_text(json.dumps(payload))

        agents_dir = tmp_path / ".agents" / "plugins"
        agents_dir.mkdir(parents=True)
        (agents_dir / "marketplace.json").write_text("{}")

        monkeypatch.setattr("custodian.codex_guard.cli.Path.cwd", lambda: tmp_path)
        monkeypatch.setattr(
            "custodian.codex_guard.cli._verify_mcp_handshake",
            lambda cmd: True,
        )

        rc = cli_main(["doctor"])
        out = capsys.readouterr().out
        assert "plugin .mcp.json" in out
        assert "in sync" in out

    def test_doctor_plugin_stale_detected(self, capsys, tmp_path, monkeypatch):
        plugin_dir = tmp_path / "plugins" / "custodian-codex-guard"
        plugin_dir.mkdir(parents=True)
        mcp = plugin_dir / ".mcp.json"
        payload = {
            "mcpServers": {
                "custodian-codex-guard": {
                    "command": "python3",
                    "args": [],
                }
            }
        }
        mcp.write_text(json.dumps(payload))

        agents_dir = tmp_path / ".agents" / "plugins"
        agents_dir.mkdir(parents=True)
        (agents_dir / "marketplace.json").write_text("{}")

        monkeypatch.setattr("custodian.codex_guard.cli.Path.cwd", lambda: tmp_path)

        rc = cli_main(["doctor"])
        out = capsys.readouterr().out
        assert "plugin .mcp.json" in out
        assert "stale" in out
        assert rc == 1

    def test_doctor_handshake_result_shown(self, capsys, tmp_path, monkeypatch):
        cwd_mcp = tmp_path / "mcp.json"
        payload = {
            "mcpServers": {
                "custodian-codex-guard": {
                    "command": sys.executable,
                    "args": ["-m", "custodian.codex_guard.mcp_server"],
                }
            }
        }
        cwd_mcp.write_text(json.dumps(payload))

        monkeypatch.setattr("custodian.codex_guard.cli.Path.cwd", lambda: tmp_path)
        monkeypatch.setattr(
            "custodian.codex_guard.cli._verify_mcp_handshake",
            lambda cmd: True,
        )

        rc = cli_main(["doctor"])
        out = capsys.readouterr().out
        assert "cwd handshake" in out
        if rc == 0:
            assert "All checks passed" in out


# ------------------------------------------------------------------
# Edge cases and compatibility
# ------------------------------------------------------------------

class TestEdgeCases:
    def test_main_returns_int(self):
        assert isinstance(cli_main(["setup", "--dry-run"]), int)

    def test_unknown_command_raises(self):
        with pytest.raises(SystemExit):
            cli_main(["unknown-command"])

    def test_verify_handshake_nonexistent_cmd(self):
        assert _verify_mcp_handshake(["/nonexistent/binary"]) is False

    def test_ensure_mcp_json_rejects_non_existent_parent(self, tmp_path):
        mcp = tmp_path / "nonexistent" / "mcp.json"
        with patch("custodian.codex_guard.cli._verify_mcp_handshake", return_value=True):
            result = _ensure_mcp_json(mcp)
        assert result is True
        assert mcp.exists()


# ------------------------------------------------------------------
# codex-guard receipts CLI
# ------------------------------------------------------------------

from custodian.codex_guard.receipts import ReceiptChain
from custodian.cli.cmd_codex_guard import run as receipts_run


def _populate_receipts(state_dir: Path, count: int = 3) -> list[dict]:
    chain = ReceiptChain(state_dir)
    records = []
    for i in range(count):
        rec = chain.append(
            {
                "verdict": "autonomous" if i % 2 == 0 else "denied",
                "action_kind": "write",
                "band": "L1",
                "reason": f"test receipt {i + 1}",
            },
            tool="test",
            session_id="test_ses",
        )
        records.append(rec)
    return records


class TestReceiptsCli:
    def test_missing_file(self, tmp_path, capsys):
        class Args:
            state_dir = str(tmp_path)
            limit = 50
            verify = False
        receipts_run(Args())
        out = capsys.readouterr().out
        assert "No codex-guard receipts found." in out

    def test_happy_path(self, tmp_path, capsys):
        _populate_receipts(tmp_path, 3)
        class Args:
            state_dir = str(tmp_path)
            limit = 50
            verify = False
        receipts_run(Args())
        out = capsys.readouterr().out
        assert "Total: 3 receipts" in out
        assert "autonomous=" in out
        assert "denied=" in out
        assert out.count("\n") >= 4  # header + 3 rows + summary

    def test_limit_one(self, tmp_path, capsys):
        _populate_receipts(tmp_path, 3)
        class Args:
            state_dir = str(tmp_path)
            limit = 1
            verify = False
        receipts_run(Args())
        out = capsys.readouterr().out
        assert "test receipt 3" in out
        assert "test receipt 2" not in out
        assert "test receipt 1" not in out
        assert "Total: 1 receipts" in out

    def test_verify_ok(self, tmp_path, capsys):
        _populate_receipts(tmp_path, 3)
        class Args:
            state_dir = str(tmp_path)
            limit = 50
            verify = True
        receipts_run(Args())
        out = capsys.readouterr().out
        assert "chain OK (3 receipts)" in out

    def test_verify_broken(self, tmp_path):
        _populate_receipts(tmp_path, 3)
        # Tamper with the second record's verdict
        path = tmp_path / "codex-guard-receipts.jsonl"
        lines = path.read_text().splitlines()
        import json as _json
        data = _json.loads(lines[1])
        data["verdict"] = "tampered"
        lines[1] = _json.dumps(data, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n")
        class Args:
            state_dir = str(tmp_path)
            limit = 50
            verify = True
        with pytest.raises(SystemExit) as exc:
            receipts_run(Args())
        assert exc.value.code == 2

    def test_malformed_line(self, tmp_path, capsys):
        _populate_receipts(tmp_path, 2)
        path = tmp_path / "codex-guard-receipts.jsonl"
        # Append a malformed line in the middle
        lines = path.read_text().splitlines()
        lines.insert(1, "not valid json")
        path.write_text("\n".join(lines) + "\n")
        class Args:
            state_dir = str(tmp_path)
            limit = 50
            verify = False
        receipts_run(Args())
        out, err = capsys.readouterr()
        assert "warning: skipping malformed line" in err
        assert "Total: 2 receipts" in out

    def test_no_color_when_redirected(self, tmp_path, capsys):
        _populate_receipts(tmp_path, 1)
        class Args:
            state_dir = str(tmp_path)
            limit = 50
            verify = False
        # capsys captures stdout (non-TTY)
        receipts_run(Args())
        out = capsys.readouterr().out
        assert "\x1b[" not in out
