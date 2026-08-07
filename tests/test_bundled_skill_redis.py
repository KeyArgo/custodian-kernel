"""Tests for the redis-set/redis-get/redis-delete bundled skills.

These scripts used to hand-build the raw Redis inline-command protocol via
unescaped f-strings (e.g. f"SET {key} {value}\\r\\n"), which let a key or
value containing "\\r\\n" inject arbitrary additional Redis commands. Fixed
by switching to the RESP array protocol, which is length-prefixed and can't
be broken out of by delimiter bytes appearing inside a value.

No test coverage existed for these scripts before this fix.

Windows CI runners with a broken Winsock provider (WinError 10106) cannot
create the local loopback socket server the tests depend on; the scripts
themselves are environment-agnostic and covered on Linux/macOS.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="GH Windows runners: WinError 10106 (Winsock provider) breaks the local socket server",
)

SKILLS_DIR = Path(__file__).resolve().parent.parent / "custodian" / "bundled_skills" / "database"


class _RecordingRedisServer:
    """A minimal fake Redis server that records the raw bytes it received."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.received = b""
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        conn.settimeout(5)
        try:
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                self.received += chunk
                conn.sendall(b"+OK\r\n")
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.sock.close()


def _run_skill(name: str, args: list) -> dict:
    script = SKILLS_DIR / name / "scripts" / "execute.py"
    result = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=10,
    )
    return json.loads(result.stdout)


def test_redis_set_escapes_crlf_in_value_via_resp_protocol():
    server = _RecordingRedisServer()
    try:
        malicious_value = "x\r\nDEL other-key\r\nSET pwned 1"
        env = {"REDIS_URL": f"redis://127.0.0.1:{server.port}"}
        result = subprocess.run(
            [sys.executable, str(SKILLS_DIR / "redis-set" / "scripts" / "execute.py"),
             "--key", "k", "--value", malicious_value],
            capture_output=True, text=True, timeout=10, env=env,
        )
        payload = json.loads(result.stdout)
        assert payload["ok"] is True

        # RESP protocol: the command is a single *3 array (SET key value),
        # and the value's byte length is declared explicitly -- so the
        # injected "\r\nDEL ...\r\nSET ..." is carried as literal payload
        # bytes inside the bulk string, never parsed as a second command.
        wire = server.received
        assert wire.startswith(b"*3\r\n$3\r\nSET\r\n")
        value_bytes = malicious_value.encode()
        assert f"${len(value_bytes)}\r\n".encode() + value_bytes + b"\r\n" in wire
        # Only one command was ever sent on the wire.
        assert wire.count(b"*3\r\n$3\r\nSET\r\n") == 1
        assert b"*2\r\n$3\r\nDEL\r\n" not in wire
    finally:
        server.close()


def test_redis_get_uses_resp_protocol_for_key():
    server = _RecordingRedisServer()
    try:
        env = {"REDIS_URL": f"redis://127.0.0.1:{server.port}"}
        malicious_key = "k\r\nFLUSHALL"
        result = subprocess.run(
            [sys.executable, str(SKILLS_DIR / "redis-get" / "scripts" / "execute.py"),
             "--key", malicious_key],
            capture_output=True, text=True, timeout=10, env=env,
        )
        json.loads(result.stdout)
        wire = server.received
        assert wire.startswith(b"*2\r\n$3\r\nGET\r\n")
        # The malicious key is carried whole, as one bulk string argument.
        key_bytes = malicious_key.encode()
        assert f"${len(key_bytes)}\r\n".encode() + key_bytes + b"\r\n" in wire
    finally:
        server.close()


def test_redis_delete_uses_resp_protocol_for_key():
    server = _RecordingRedisServer()
    try:
        env = {"REDIS_URL": f"redis://127.0.0.1:{server.port}"}
        malicious_key = "k\r\nCONFIG SET requirepass hacked"
        result = subprocess.run(
            [sys.executable, str(SKILLS_DIR / "redis-delete" / "scripts" / "execute.py"),
             "--key", malicious_key],
            capture_output=True, text=True, timeout=10, env=env,
        )
        json.loads(result.stdout)
        wire = server.received
        assert wire.startswith(b"*2\r\n$3\r\nDEL\r\n")
        key_bytes = malicious_key.encode()
        assert f"${len(key_bytes)}\r\n".encode() + key_bytes + b"\r\n" in wire
    finally:
        server.close()


def test_redis_set_without_url_is_a_harmless_stub():
    out = _run_skill("redis-set", ["--key", "k", "--value", "v"])
    assert out == {
        "ok": False, "stub": True, "tool": "redis-set",
        "message": "Set REDIS_URL to enable",
    }
