"""The client shim a sandboxed tool imports to make authenticated calls
*without ever holding the credential*.

Inside the sandbox there is no network except the Unix socket to Paladin's
:class:`paladin.egress.EgressGateway`. A tool builds an unauthenticated
request (method, url, which ref to use, and where to inject it) and gets
back ``{status, headers, body}``. The secret is attached on the host side
by the broker and never enters this process.

Deliberately stdlib-only and free of any ``paladin`` heavy imports (no
vault, no ``cryptography``): importing this in a locked-down sandbox must
never require the crypto stack. The gateway imports its framing helpers
from here, not the other way around.

Typical use inside a tool::

    from paladin.egress_client import Session
    s = Session()                      # reads PALADIN_EGRESS_SOCK / _TOKEN
    r = s.post(
        "https://api.stripe.com/v1/refunds",
        ref="stripe_sk",
        inject={"header": "Authorization", "format": "Bearer {value}"},
        body="charge=ch_123&amount=500",
    )
    print(r["status"], r["body"])      # the key was never in this process
"""
from __future__ import annotations

import json
import os
import socket
import struct
from typing import Optional

TOKEN_ENV = "PALADIN_EGRESS_TOKEN"
SOCK_ENV = "PALADIN_EGRESS_SOCK"
REFS_ENV = "PALADIN_EGRESS_REFS"

_MAX_FRAME = 16 * 1024 * 1024


class EgressError(Exception):
    """A sandboxed egress call was refused or failed. The message is
    value-free (it comes from the broker, which never puts a secret in an
    error)."""


def _recv_exactly(sock: socket.socket, n: int) -> Optional[bytes]:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


def send_frame(sock: socket.socket, obj: dict) -> None:
    data = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock: socket.socket) -> Optional[dict]:
    hdr = _recv_exactly(sock, 4)
    if hdr is None:
        return None
    (n,) = struct.unpack(">I", hdr)
    if n > _MAX_FRAME:
        raise ValueError("egress frame too large")
    data = _recv_exactly(sock, n)
    if data is None:
        return None
    return json.loads(data.decode("utf-8"))


class Session:
    """A connection factory to the per-run egress gateway."""

    def __init__(self, socket_path: Optional[str] = None,
                 token: Optional[str] = None) -> None:
        self.socket_path = socket_path or os.environ.get(SOCK_ENV)
        self.token = token or os.environ.get(TOKEN_ENV)
        if not self.socket_path or not self.token:
            raise EgressError(
                "no egress gateway in environment "
                f"(set {SOCK_ENV} and {TOKEN_ENV}, or run under `paladin exec --sandbox`)"
            )

    def allowed_refs(self) -> set:
        """The ref names this run was scoped to (if any), from the env."""
        raw = os.environ.get(REFS_ENV, "")
        return {r for r in raw.split(",") if r}

    def request(self, method: str, url: str, ref: str, inject: dict,
                headers: Optional[dict] = None, body=None) -> dict:
        frame = {
            "token": self.token,
            "request": {
                "method": method, "url": url, "ref": ref, "inject": inject,
                "headers": headers or {}, "body": body,
            },
        }
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(self.socket_path)
            send_frame(s, frame)
            resp = recv_frame(s)
        if resp is None:
            raise EgressError("egress gateway closed the connection")
        if resp.get("error"):
            raise EgressError(f"{resp.get('code', 'error')}: {resp['error']}")
        return resp["response"]

    def get(self, url: str, ref: str, inject: dict, **kw) -> dict:
        return self.request("GET", url, ref, inject, **kw)

    def post(self, url: str, ref: str, inject: dict, **kw) -> dict:
        return self.request("POST", url, ref, inject, **kw)
