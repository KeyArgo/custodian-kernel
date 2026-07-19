"""The egress gateway — pure transport between a sandboxed child and the
Broker's authenticated-egress choke point.

This process runs on the *host* side (it has network; the sandboxed child
does not). It listens on a Unix-domain socket, reads one unauthenticated
request descriptor per connection, hands it to
:meth:`paladin.broker.Broker.egress_request` (which does all grant/host
checks, resolves the secret, injects it, and makes the outbound call), and
writes back ``{status, headers, body}``. **The gateway never sees a secret
value** — the plaintext lives and dies inside ``egress_request``.

Two things gate who may use the socket:

1. **Filesystem** — the socket sits in a 0700 directory, so only the same
   uid can reach it at all.
2. **A per-run session token** — a random token minted at ``start()`` and
   handed to the child via the ``PALADIN_EGRESS_TOKEN`` env var inside the
   sandbox. Every request frame must present it (constant-time compared),
   so another same-uid process that stumbles onto the live socket still
   can't drive granted egress. This token is NOT a vault secret; it is a
   capability for this one run.
"""
from __future__ import annotations

import hmac
import os
import secrets
import socket
import tempfile
import threading
from pathlib import Path
from typing import Optional

from paladin.broker import Broker, DEFAULT_EGRESS_TIMEOUT
from paladin.egress_client import (
    REFS_ENV,
    SOCK_ENV,
    TOKEN_ENV,
    recv_frame,
    send_frame,
)
from paladin.errors import PaladinError


class EgressGateway:
    """A running gateway for one sandboxed run, bound to one requester/band."""

    def __init__(self, broker: Broker, requester: str, band: str = "L0",
                 allow_refs: Optional[set] = None,
                 timeout: float = DEFAULT_EGRESS_TIMEOUT,
                 socket_dir: Optional[Path] = None) -> None:
        self.broker = broker
        self.requester = requester
        self.band = band
        self.allow_refs = set(allow_refs) if allow_refs is not None else None
        self.timeout = timeout
        self.token = secrets.token_urlsafe(32)
        self._owns_dir = socket_dir is None
        self._dir = Path(socket_dir) if socket_dir else Path(tempfile.mkdtemp(prefix="paladin-egress-"))
        os.chmod(self._dir, 0o700)
        self.socket_path = str(self._dir / "egress.sock")
        self._srv: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> str:
        # The gateway is a Unix-domain-socket transport, so it is POSIX-only.
        # On Windows socket.AF_UNIX does not exist; fail with the module's own
        # clean error rather than a bare AttributeError, so a `--sandbox`
        # request on Windows reports "sandbox unavailable" and fails closed.
        if not hasattr(socket, "AF_UNIX"):
            from paladin.errors import SandboxUnavailableError
            raise SandboxUnavailableError(
                "sandboxed egress requires Unix domain sockets (POSIX only); "
                "this platform has no socket.AF_UNIX")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        srv.listen(16)
        srv.settimeout(0.5)  # so the accept loop can observe _stop
        self._srv = srv
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self.socket_path

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._srv:
            self._srv.close()
            self._srv = None
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass
        if self._owns_dir:
            try:
                os.rmdir(self._dir)
            except OSError:
                pass

    def __enter__(self) -> "EgressGateway":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def child_env(self) -> dict:
        """The env vars a sandboxed child needs to reach this gateway. None
        of these is a vault secret — a socket path, a session token, and the
        allowed ref names."""
        env = {SOCK_ENV: self.socket_path, TOKEN_ENV: self.token}
        if self.allow_refs is not None:
            env[REFS_ENV] = ",".join(sorted(self.allow_refs))
        return env

    # -- serving -------------------------------------------------------------

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(self.timeout + 5.0)
        try:
            req = recv_frame(conn)
            if req is None:
                return
            if not isinstance(req, dict) or not hmac.compare_digest(
                str(req.get("token", "")), self.token
            ):
                send_frame(conn, {"error": "bad or missing session token",
                                  "code": "unauthorized"})
                return
            try:
                result = self.broker.egress_request(
                    req.get("request", {}), requester=self.requester,
                    band=self.band, allow_refs=self.allow_refs,
                    timeout=self.timeout)
                send_frame(conn, {"ok": True, "response": result})
            except PaladinError as e:
                # Broker errors are value-free by construction — safe to relay.
                send_frame(conn, {"error": str(e), "code": type(e).__name__})
            except Exception:  # noqa: BLE001 — never leak an upstream traceback
                send_frame(conn, {"error": "egress failed", "code": "internal"})
        finally:
            conn.close()
