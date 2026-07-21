"""Per-tool destination-allowlist egress proxy.

Threat model, stated plainly (read this before trusting it for anything):
this is NOT network isolation. custodian/sandbox.py's bwrap wrapper
deliberately does not unshare the network namespace (see its own
docstring), so a governed tool's subprocess still has full, raw network
access at the OS level. This proxy only redirects *cooperative* HTTP
clients -- anything that honors the HTTP_PROXY/HTTPS_PROXY environment
variables, which is most ordinary API-calling code (requests, urllib,
curl, most SDKs) -- through a local checkpoint that refuses to connect
anywhere the tool didn't declare. A compromised script that opens a raw
socket directly, ignoring the proxy env vars entirely, is not stopped by
this at all.

That's a real, meaningful improvement over today's status quo (zero
destination control whatsoever) without the scope of real network
isolation (bwrap --unshare-net + an authorizing egress gateway, deferred
to its own 0.6.0 branch -- see the production-readiness task list). It
closes off the common case -- a tool's own SDK exfiltrating to an
attacker-controlled host -- while leaving the harder case (a fully
malicious payload bypassing its own HTTP client) for that later work.

Usage: a skill opts in by declaring allowed_hosts in its SKILL.md
custodian metadata:

    metadata:
      custodian:
        band: L2
        allowed_hosts: ["api.stripe.com"]

A tool that declares no allowed_hosts gets no restriction at all --
opt-in only, so every existing skill's behavior is unchanged unless it's
updated to declare its real destinations.
"""
from __future__ import annotations

import http.server
import select
import socket
import socketserver
import threading
from typing import FrozenSet, Optional
from urllib.parse import urlsplit


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """Bidirectionally relay bytes between two sockets until either closes
    or a receive fails."""
    sockets = [a, b]
    try:
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional or not readable:
                break
            done = False
            for s in readable:
                other = b if s is a else a
                try:
                    data = s.recv(65536)
                except OSError:
                    done = True
                    break
                if not data:
                    done = True
                    break
                try:
                    other.sendall(data)
                except OSError:
                    done = True
                    break
            if done:
                break
    finally:
        for s in (a, b):
            try:
                s.close()
            except OSError:
                pass


def _make_handler(proxy: "EgressProxy"):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args) -> None:  # quiet by default
            pass

        def do_CONNECT(self) -> None:
            host, _, port_s = self.path.partition(":")
            try:
                port = int(port_s or 443)
            except ValueError:
                self.send_error(400, "invalid CONNECT target")
                return
            if not proxy.is_allowed(host):
                self.send_error(403, f"destination not allowed by this tool's egress policy: {host}")
                return
            try:
                upstream = socket.create_connection((host, port), timeout=10)
            except OSError as e:
                self.send_error(502, f"could not reach {host}:{port}: {e}")
                return
            self.send_response(200, "Connection Established")
            self.end_headers()
            _pipe(self.connection, upstream)

        def _forward(self, method: str) -> None:
            parts = urlsplit(self.path)
            host = parts.hostname
            if not host or not proxy.is_allowed(host):
                self.send_error(403, f"destination not allowed by this tool's egress policy: {host}")
                return
            port = parts.port or 80
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
            except ValueError:
                length = 0
            body = self.rfile.read(length) if length else b""
            try:
                upstream = socket.create_connection((host, port), timeout=10)
            except OSError as e:
                self.send_error(502, f"could not reach {host}:{port}: {e}")
                return
            path = parts.path or "/"
            if parts.query:
                path += f"?{parts.query}"
            request_line = f"{method} {path} HTTP/1.1\r\n".encode()
            header_bytes = b""
            for k, v in self.headers.items():
                if k.lower() == "proxy-connection":
                    continue
                header_bytes += f"{k}: {v}\r\n".encode()
            try:
                upstream.sendall(request_line + header_bytes + b"\r\n" + body)
                response = bytearray()
                while True:
                    chunk = upstream.recv(65536)
                    if not chunk:
                        break
                    response.extend(chunk)
                self.connection.sendall(bytes(response))
            finally:
                upstream.close()

        def do_GET(self) -> None: self._forward("GET")
        def do_POST(self) -> None: self._forward("POST")
        def do_PUT(self) -> None: self._forward("PUT")
        def do_DELETE(self) -> None: self._forward("DELETE")
        def do_PATCH(self) -> None: self._forward("PATCH")
        def do_HEAD(self) -> None: self._forward("HEAD")

    return Handler


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class EgressProxy:
    """An ephemeral local HTTP/HTTPS forward proxy scoped to one governed
    tool subprocess call. See module docstring for the threat model this
    does and does not cover."""

    def __init__(self, allowed_hosts: FrozenSet[str] = frozenset()):
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self._server = _Server(("127.0.0.1", 0), _make_handler(self))
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def is_allowed(self, host: str) -> bool:
        """No declared allowlist means no restriction -- opt-in only, so a
        tool that hasn't been updated with allowed_hosts keeps today's
        unrestricted behavior."""
        if not self.allowed_hosts:
            return True
        return host.lower() in self.allowed_hosts

    def start(self) -> None:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "EgressProxy":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def proxy_env(self) -> dict:
        addr = f"http://127.0.0.1:{self.port}"
        return {
            "HTTP_PROXY": addr, "HTTPS_PROXY": addr,
            "http_proxy": addr, "https_proxy": addr,
        }
