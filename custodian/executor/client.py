"""Agent-side client for the delegated executor.

This is the entire capability surface the calling agent's process has: open
a socket, send a JSON request, read a JSON response. There is no
subprocess/exec code anywhere in this file, on purpose -- an agent process
that only ever imports custodian.executor.client cannot run a governed
skill script itself under any circumstance, compromised or not. It can only
ask a separate process (custodian.executor.service, running independently)
to do it, and that process re-derives its own decision every time.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Optional

from custodian.exceptions import CustodianError


class ExecutorUnavailableError(CustodianError):
    """The executor process is not reachable at the configured socket."""


class ExecutorClient:
    def __init__(self, socket_path: Path, timeout: float = 35.0) -> None:
        self.socket_path = Path(socket_path)
        self.timeout = timeout

    def propose(self, tool: str, args: dict, *, requester: str,
               workspace: str = "", credential_refs: list[str] | None = None,
               env: Optional[dict] = None) -> dict:
        if env:
            return {
                "ok": False, "verdict": "denied",
                "error": "client environment injection is forbidden; use paladin:// references",
            }
        payload = {
            "tool": tool, "args": args, "requester": requester,
            "workspace": workspace, "credential_refs": credential_refs or [],
        }
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(str(self.socket_path))
                sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
                sock.shutdown(socket.SHUT_WR)
                chunks = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
        except (OSError, socket.timeout) as e:
            raise ExecutorUnavailableError(
                f"executor at {self.socket_path} is not reachable: {e}"
            ) from e
        raw = b"".join(chunks).strip()
        if not raw:
            raise ExecutorUnavailableError("executor closed the connection with no response")
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ExecutorUnavailableError(f"executor returned an unparseable response: {e}") from e
