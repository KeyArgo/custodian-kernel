"""The delegated executor: a separate OS process that holds the only code
path allowed to actually run a governed skill script.

Listens on a Unix domain socket for newline-delimited JSON requests. Every
decision is re-derived here, independently, from this process's own copy of
the tool registry and kernel policy state -- never from anything the client
claims about a tool's band or cost. A client (custodian.executor.client)
can only ask; it cannot execute anything itself.

    {"tool": "stripe-spend", "args": {"amount": 5.0}, "requester": "session:abc"}
      -> {"ok": true, ...}                                    (autonomous)
      -> {"ok": false, "verdict": "escalation_required",
          "capability_id": "...", "reason": "..."}             (needs a human)
      -> {"ok": false, "verdict": "denied", "reason": "..."}   (kill switch / hard cap)

Re-sending the *exact same* request after a human has approved the
capability (via ``custodian executor approve <id>``) consumes it atomically
and executes -- exactly once.
"""
from __future__ import annotations

import json
import os
import socket
import socketserver
import threading
from pathlib import Path
from typing import Optional

from custodian.executor.capability import CapabilityError, CapabilityStore, action_digest
from custodian.tools.registry import ToolRegistry, _state_dir


class ExecutorService:
    """The decision-making and execution core, independent of the socket
    transport -- kept separate so tests can drive it directly without
    spawning a real process, while custodian/executor/service.py's __main__
    entry point (the actual separate process a deployment runs) wraps it in
    the socket server below."""

    def __init__(self, skills_root: Path, state_dir: Optional[Path] = None,
                default_ttl_seconds: int = 600) -> None:
        self.registry = ToolRegistry(skills_root)
        self.state_dir = state_dir or _state_dir()
        self.capabilities = CapabilityStore(self.state_dir)
        self.default_ttl_seconds = default_ttl_seconds

    def handle(self, payload: dict) -> dict:
        tool_name = payload.get("tool")
        args = dict(payload.get("args") or {})
        # Truncate to the SAME length CapabilityStore.request() uses
        # internally (capability.py's requester[:128]) -- a mismatch here
        # (this used to truncate at 256) meant a requester string longer
        # than 128 chars got stored shorter than the value later compared
        # against in find_pending_by_digest()/consume(), so an approved
        # capability could never be found/consumed again: the resend loop
        # silently issued a fresh escalation forever instead of executing
        # the one the operator had just approved.
        requester = str(payload.get("requester") or "executor-client")[:128]
        workspace = str(payload.get("workspace") or "")
        if "env" in payload:
            return {"ok": False, "verdict": "denied", "error": "client environment injection is forbidden"}
        credential_refs = payload.get("credential_refs") or []
        if not isinstance(credential_refs, list) or any(
            not isinstance(ref, str) or not ref.startswith("paladin://")
            for ref in credential_refs
        ):
            return {"ok": False, "verdict": "denied", "error": "invalid credential reference"}
        # Resolution belongs behind this boundary. Fail closed until a
        # server-owned Paladin resolver is configured.
        if credential_refs:
            return {"ok": False, "verdict": "denied", "error": "executor credential resolver is not configured"}
        env = None

        tool = self.registry.get(tool_name) if tool_name else None
        if tool is None:
            return {"ok": False, "error": f"tool not found: {tool_name}", "tool": tool_name}

        from custodian.tools.registry import _is_configured
        if not _is_configured(tool.name, tool.configured, env=env):
            return {
                "ok": False, "stub": True, "tool": tool.name,
                "message": f"{tool.name} is not configured",
            }

        try:
            real_amount = float(args.get("amount", tool.cost_usd) or 0)
        except (TypeError, ValueError):
            real_amount = tool.cost_usd

        digest = action_digest(tool=tool.name, args=args, workspace=workspace,
                               requester=requester)

        if tool.band in ("L2", "L3", "L4"):
            decision = tool._kernel_decide(real_amount)
            verdict = decision["verdict"] if decision else "escalation_required"
            reason = decision["reason"] if decision else "kernel decision unavailable"

            if verdict == "denied":
                return {
                    "ok": False, "verdict": "denied", "reason": reason,
                    "tool": tool.name, "band": tool.band,
                }

            if verdict != "autonomous":
                # Escalated: has a human already approved *this exact*
                # action? If so, consume the capability now (exactly once)
                # and fall through to execution. If not, register (or find)
                # a pending capability and hand its id back -- nothing
                # executes until a human approves it.
                existing = self.capabilities.find_pending_by_digest(digest, requester)
                if existing is not None and existing.is_approved:
                    try:
                        self.capabilities.consume(existing.capability_id,
                                                  digest=digest, requester=requester)
                    except CapabilityError as e:
                        return {
                            "ok": False, "kernel_escalation": True,
                            "verdict": "escalation_required",
                            "reason": f"approved capability could not be consumed: {e}",
                            "tool": tool.name, "band": tool.band,
                        }
                    # approved and consumed -- proceed to execution below
                else:
                    if existing is None:
                        existing = self.capabilities.request(
                            digest=digest, requester=requester,
                            ttl_seconds=self.default_ttl_seconds,
                        )
                    return {
                        "ok": False, "kernel_escalation": True,
                        "verdict": "escalation_required", "reason": reason,
                        "tool": tool.name, "band": tool.band,
                        "capability_id": existing.capability_id,
                        "message": (
                            f"Escalation required for {tool.name}: {reason}. "
                            f"Approve with: custodian executor approve "
                            f"{existing.capability_id} --approved-by <name>, "
                            f"then resend the identical request."
                        ),
                    }

        return tool._run_script(args, env)


def _read_line(conn: socket.socket) -> Optional[bytes]:
    chunks = []
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            return None
        chunks.append(chunk)
        if b"\n" in chunk:
            return b"".join(chunks).split(b"\n", 1)[0]


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        service: ExecutorService = self.server.executor_service  # type: ignore[attr-defined]
        try:
            line = _read_line(self.request)
            if line is None:
                return
            payload = json.loads(line.decode("utf-8"))
            response = service.handle(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            response = {"ok": False, "error": f"invalid request: {e}"}
        except Exception as e:
            response = {"ok": False, "error": f"executor error: {type(e).__name__}: {e}"}
        try:
            self.request.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except OSError:
            pass


class ExecutorServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, socket_path: Path, service: ExecutorService) -> None:
        self.executor_service = service
        if socket_path.exists():
            socket_path.unlink()
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(str(socket_path), _Handler)
        os.chmod(socket_path, 0o600)


def serve_forever(skills_root: Path, socket_path: Path, state_dir: Optional[Path] = None) -> None:
    """Entry point for the separate executor process (e.g. `custodian
    executor start`). Blocks forever."""
    service = ExecutorService(skills_root, state_dir=state_dir)
    server = ExecutorServer(socket_path, service)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if socket_path.exists():
            socket_path.unlink()
