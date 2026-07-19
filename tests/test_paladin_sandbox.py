"""Sandboxed-egress OS-isolation tests (Linux + bwrap).

Hostile corpus: prove that a child launched via spawn_sandboxed()
  * has NO secret value anywhere in its environment or /proc/self/environ,
  * cannot reach the network directly (only the gateway UDS),
  * CAN make an authenticated call through the gateway (secret attached
    host-side), and
  * does not inherit the parent's PALADIN_PASSPHRASE / PALADIN_KEYFILE.
Plus: the runner fails closed when the sandbox is unavailable.
"""
import http.server
import textwrap
import threading

import pytest

from paladin.vault import Vault
from paladin.broker import Broker
from paladin.sandbox import spawn_sandboxed, sandbox_available
from paladin.errors import SandboxUnavailableError

pytestmark = pytest.mark.skipif(
    not sandbox_available(),
    reason="bwrap / unprivileged user namespaces unavailable",
)

PP = "test-passphrase-123"
SECRET = "sk_live_super_secret_value_1234567890"


@pytest.fixture
def broker(tmp_path):
    v = Vault.create(path=tmp_path / "v.paladin", passphrase=PP)
    v.add("api_key", SECRET, allowed_hosts=["127.0.0.1"])
    b = Broker(v)
    b.grant("api_key", "sandbox:t", max_band="L2")
    return b


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    seen_auth = None

    def do_GET(self):
        type(self).seen_auth = self.headers.get("Authorization")
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def http_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _EchoHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _EchoHandler.seen_auth = None
    yield srv
    srv.shutdown()


def test_secret_absent_from_child_env_and_proc(broker, monkeypatch):
    # Parent even holds the passphrase in its own env — the child must not
    # inherit it.
    monkeypatch.setenv("PALADIN_PASSPHRASE", PP)
    script = textwrap.dedent("""
        import os
        env = dict(os.environ)
        blob = repr(env)
        try:
            with open("/proc/self/environ", "rb") as f:
                blob += f.read().decode("latin-1")
        except OSError:
            pass
        marker = "sk_live_super_secret_value_1234567890"
        print("SECRET_PRESENT" if marker in blob else "SECRET_ABSENT")
        print("PASSPHRASE_PRESENT" if "PALADIN_PASSPHRASE" in env else "PASSPHRASE_ABSENT")
    """)
    r = spawn_sandboxed(["python3", "-c", script], broker,
                        requester="sandbox:t", band="L1", allow_refs={"api_key"})
    assert "SECRET_ABSENT" in r.stdout
    assert "PASSPHRASE_ABSENT" in r.stdout


def test_child_cannot_reach_network_directly(broker, http_server):
    port = http_server.server_address[1]
    script = textwrap.dedent(f"""
        import socket
        try:
            socket.create_connection(("127.0.0.1", {port}), timeout=3)
            print("CONNECTED")
        except OSError as e:
            print("BLOCKED", type(e).__name__)
    """)
    r = spawn_sandboxed(["python3", "-c", script], broker,
                        requester="sandbox:t", band="L1", allow_refs={"api_key"})
    assert "BLOCKED" in r.stdout
    assert "CONNECTED" not in r.stdout


def test_child_can_call_through_gateway(broker, http_server):
    port = http_server.server_address[1]
    script = textwrap.dedent(f"""
        from paladin.egress_client import Session
        s = Session()
        r = s.get("http://127.0.0.1:{port}/thing", ref="api_key",
                  inject={{"header": "Authorization", "format": "Bearer {{value}}"}})
        print("STATUS", r["status"])
        print("SECRET_IN_BODY" if "sk_live" in r["body"] else "CLEAN_BODY")
    """)
    r = spawn_sandboxed(["python3", "-c", script], broker,
                        requester="sandbox:t", band="L1", allow_refs={"api_key"})
    assert "STATUS 200" in r.stdout, r.stderr
    assert "CLEAN_BODY" in r.stdout
    # The upstream server saw the injected credential the child never held.
    assert _EchoHandler.seen_auth == f"Bearer {SECRET}"


def test_child_cannot_read_vault_files(broker):
    # The vault + keyfile dir are masked; the child sees them empty.
    vault_dir = str(broker.vault.path.parent)
    script = textwrap.dedent(f"""
        import os
        try:
            listing = os.listdir({vault_dir!r})
        except OSError:
            listing = ["<unreadable>"]
        print("VAULT_VISIBLE" if any("paladin" in x for x in listing) else "VAULT_MASKED")
    """)
    r = spawn_sandboxed(["python3", "-c", script], broker,
                        requester="sandbox:t", band="L1", allow_refs={"api_key"})
    assert "VAULT_MASKED" in r.stdout


def test_fails_closed_when_sandbox_unavailable(broker, monkeypatch):
    import paladin.sandbox as sb
    monkeypatch.setattr(sb, "sandbox_available", lambda: False)
    with pytest.raises(SandboxUnavailableError):
        spawn_sandboxed(["true"], broker, requester="sandbox:t")
