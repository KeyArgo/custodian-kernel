"""Tests for custodian.egress_proxy.EgressProxy.

Threat-model reminder (see the module docstring): this only redirects
cooperative HTTP clients honoring HTTP_PROXY/HTTPS_PROXY. These tests
prove that redirection actually enforces the declared allowlist -- they
do not, and cannot, prove anything about a client that ignores the proxy
env vars and opens a raw socket directly (there is nothing to prove:
nothing here stops that, by design, and the module docstring says so).
"""
from __future__ import annotations

import http.server
import socket
import threading
import urllib.error
import urllib.request
from urllib.request import ProxyHandler, build_opener

import pytest

from custodian.egress_proxy import EgressProxy


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        body = b"hello from destination"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def destination():
    """A real local HTTP server acting as the tool's intended destination."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _get_through_proxy(proxy: EgressProxy, url: str) -> bytes:
    opener = build_opener(ProxyHandler({"http": f"http://127.0.0.1:{proxy.port}"}))
    with opener.open(url, timeout=5) as resp:
        return resp.read()


def test_allowed_host_is_reachable_through_the_proxy(destination):
    host, port = destination.server_address
    with EgressProxy(allowed_hosts=frozenset({host})) as proxy:
        body = _get_through_proxy(proxy, f"http://{host}:{port}/")
        assert body == b"hello from destination"


def test_undeclared_host_is_refused(destination):
    host, port = destination.server_address
    with EgressProxy(allowed_hosts=frozenset({"totally-different-host.example"})) as proxy:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get_through_proxy(proxy, f"http://{host}:{port}/")
        assert exc.value.code == 403


def test_empty_allowlist_means_unrestricted(destination):
    """Opt-in only: a tool that hasn't declared allowed_hosts keeps today's
    unrestricted behavior."""
    host, port = destination.server_address
    with EgressProxy(allowed_hosts=frozenset()) as proxy:
        body = _get_through_proxy(proxy, f"http://{host}:{port}/")
        assert body == b"hello from destination"


def test_host_matching_is_case_insensitive():
    proxy = EgressProxy(allowed_hosts=frozenset({"API.Stripe.COM"}))
    assert proxy.is_allowed("api.stripe.com") is True
    assert proxy.is_allowed("API.STRIPE.COM") is True
    assert proxy.is_allowed("evil.example") is False


def test_connect_tunnel_relays_bytes_when_allowed():
    """CONNECT-tunneled traffic (the HTTPS case) is a raw bidirectional
    relay once permitted -- tested here against a plain TCP echo server
    rather than a real TLS endpoint, since the tunnel itself is
    protocol-agnostic; the proxy never inspects what flows through it,
    only whether the destination host was declared."""
    echo_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    echo_server.bind(("127.0.0.1", 0))
    echo_server.listen(1)
    echo_host, echo_port = echo_server.getsockname()

    def echo_once():
        conn, _ = echo_server.accept()
        data = conn.recv(1024)
        conn.sendall(data)
        conn.close()

    threading.Thread(target=echo_once, daemon=True).start()

    with EgressProxy(allowed_hosts=frozenset({echo_host})) as proxy:
        client = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
        client.sendall(f"CONNECT {echo_host}:{echo_port} HTTP/1.1\r\n\r\n".encode())
        response = client.recv(1024)
        assert b"200" in response

        client.sendall(b"ping-through-tunnel")
        echoed = client.recv(1024)
        assert echoed == b"ping-through-tunnel"
        client.close()
    echo_server.close()


def test_connect_tunnel_refused_for_undeclared_host():
    echo_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    echo_server.bind(("127.0.0.1", 0))
    echo_server.listen(1)
    echo_host, echo_port = echo_server.getsockname()

    with EgressProxy(allowed_hosts=frozenset({"someone-elses-host.example"})) as proxy:
        client = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
        client.sendall(f"CONNECT {echo_host}:{echo_port} HTTP/1.1\r\n\r\n".encode())
        response = client.recv(1024)
        assert b"403" in response
        client.close()
    echo_server.close()


def test_proxy_env_points_at_the_running_port():
    with EgressProxy(allowed_hosts=frozenset()) as proxy:
        env = proxy.proxy_env()
        assert env["HTTP_PROXY"] == f"http://127.0.0.1:{proxy.port}"
        assert env["HTTPS_PROXY"] == env["HTTP_PROXY"]
