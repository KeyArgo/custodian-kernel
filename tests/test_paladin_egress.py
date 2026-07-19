"""Sandboxed-egress gateway tests (host side, no bwrap required).

These prove the broker's authenticated-egress choke point and the UDS
gateway/client transport: the credential is attached on the host side and
the child-facing surface (descriptor in, {status,headers,body} out) never
carries the value. The actual OS isolation is exercised separately in
test_paladin_sandbox.py (Linux + bwrap gated)."""
import http.server
import threading

import pytest

from paladin.vault import Vault
from paladin.broker import Broker
from paladin.egress import EgressGateway
from paladin.egress_client import Session, EgressError

PP = "test-passphrase-123"
SECRET = "sk_live_super_secret_value_1234567890"


@pytest.fixture
def vault(tmp_path):
    return Vault.create(path=tmp_path / "v.paladin", passphrase=PP)


@pytest.fixture
def broker(vault):
    return Broker(vault)


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    """Records the auth header it saw and echoes a fixed body."""

    seen_auth = None
    seen_path = None

    def _respond(self):
        type(self).seen_auth = self.headers.get("Authorization")
        type(self).seen_path = self.path
        body = b'{"ok": true, "note": "no secret here"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _respond
    do_POST = _respond

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def http_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _EchoHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    _EchoHandler.seen_auth = None
    _EchoHandler.seen_path = None
    yield srv
    srv.shutdown()


def _host_port(srv):
    return f"127.0.0.1:{srv.server_address[1]}"


def test_gateway_injects_credential_child_never_sees_it(broker, vault, http_server):
    vault.add("api_key", SECRET, allowed_hosts=["127.0.0.1"])
    broker.grant("api_key", "sandbox:t", max_band="L2")
    with EgressGateway(broker, requester="sandbox:t", band="L1",
                       allow_refs={"api_key"}) as gw:
        s = Session(socket_path=gw.socket_path, token=gw.token)
        r = s.get(
            f"http://{_host_port(http_server)}/v1/thing",
            ref="api_key",
            inject={"header": "Authorization", "format": "Bearer {value}"},
        )
    # The upstream server received the injected credential...
    assert _EchoHandler.seen_auth == f"Bearer {SECRET}"
    # ...but the child-facing response never contains the raw value.
    assert SECRET not in r["body"]
    assert SECRET not in str(r["headers"])
    assert r["status"] == 200


def test_wrong_host_denied_before_resolve(broker, vault, http_server):
    vault.add("api_key", SECRET, allowed_hosts=["api.stripe.com"])
    broker.grant("api_key", "sandbox:t", max_band="L2")
    with EgressGateway(broker, requester="sandbox:t") as gw:
        s = Session(socket_path=gw.socket_path, token=gw.token)
        with pytest.raises(EgressError):
            s.get(f"http://{_host_port(http_server)}/x", ref="api_key",
                  inject={"header": "Authorization", "format": "Bearer {value}"})
    # Nothing was sent upstream.
    assert _EchoHandler.seen_auth is None


def test_ungranted_ref_denied_and_audited(broker, vault, http_server):
    vault.add("api_key", SECRET, allowed_hosts=["127.0.0.1"])
    # no grant issued
    with EgressGateway(broker, requester="sandbox:t") as gw:
        s = Session(socket_path=gw.socket_path, token=gw.token)
        with pytest.raises(EgressError):
            s.get(f"http://{_host_port(http_server)}/x", ref="api_key",
                  inject={"header": "Authorization", "format": "Bearer {value}"})
    events = [r["event"] for r in broker.audit.records()]
    assert "deny" in events
    assert "egress" not in events


def test_bad_token_rejected(broker, vault, http_server):
    vault.add("api_key", SECRET, allowed_hosts=["127.0.0.1"])
    broker.grant("api_key", "sandbox:t", max_band="L2")
    with EgressGateway(broker, requester="sandbox:t") as gw:
        s = Session(socket_path=gw.socket_path, token="not-the-real-token")
        with pytest.raises(EgressError):
            s.get(f"http://{_host_port(http_server)}/x", ref="api_key",
                  inject={"header": "Authorization", "format": "Bearer {value}"})


def test_grant_scope_narrows_method(broker, vault, http_server):
    vault.add("api_key", SECRET, allowed_hosts=["127.0.0.1"])
    # grant permits GET only
    broker.grants.grant("api_key", "sandbox:t", max_band="L2")
    g = broker.grants.list()[0]
    g.methods = ["GET"]
    broker.vault.set_raw_grants([__import__("dataclasses").asdict(g)])
    broker.grants = type(broker.grants)(broker.vault)  # reload
    with EgressGateway(broker, requester="sandbox:t") as gw:
        s = Session(socket_path=gw.socket_path, token=gw.token)
        # GET allowed
        s.get(f"http://{_host_port(http_server)}/ok", ref="api_key",
              inject={"header": "Authorization", "format": "Bearer {value}"})
        # POST denied by grant scope
        with pytest.raises(EgressError):
            s.post(f"http://{_host_port(http_server)}/x", ref="api_key",
                   inject={"header": "Authorization", "format": "Bearer {value}"})


def test_concurrent_egress_keeps_audit_chain_intact(broker, vault, http_server):
    # The gateway serves a thread per connection; concurrent egress calls
    # must not fork the audit hash chain (regression for the in-process race).
    import threading
    vault.add("api_key", SECRET, allowed_hosts=["127.0.0.1"])
    broker.grant("api_key", "sandbox:t", max_band="L2")
    errors = []
    with EgressGateway(broker, requester="sandbox:t", band="L1") as gw:
        def hammer():
            s = Session(socket_path=gw.socket_path, token=gw.token)
            try:
                for _ in range(10):
                    s.get(f"http://{_host_port(http_server)}/x", ref="api_key",
                          inject={"header": "Authorization", "format": "Bearer {value}"})
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=hammer) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    assert not errors, errors
    # 60 egress records + grant, all chained correctly.
    assert broker.audit.verify() >= 60


def test_child_supplied_auth_header_cannot_shadow_injection(broker, vault, http_server):
    vault.add("api_key", SECRET, allowed_hosts=["127.0.0.1"])
    broker.grant("api_key", "sandbox:t", max_band="L2")
    with EgressGateway(broker, requester="sandbox:t") as gw:
        s = Session(socket_path=gw.socket_path, token=gw.token)
        s.get(f"http://{_host_port(http_server)}/x", ref="api_key",
              headers={"authorization": "Bearer attacker-controlled"},
              inject={"header": "Authorization", "format": "Bearer {value}"})
    assert _EchoHandler.seen_auth == f"Bearer {SECRET}"
