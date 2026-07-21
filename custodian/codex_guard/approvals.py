"""Action-bound, expiring, single-use approvals for Codex Guard.

Approval records persist only a digest and bounded metadata. Proposed commands,
arguments, prompts, file contents, and secret references are never written.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import time
from typing import Any
from uuid import uuid4


class ApprovalError(ValueError):
    """An approval is missing, invalid, expired, changed, or already used."""


def _private_dir(path: Path) -> None:
    """Create a private state directory and reject symlink redirection."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ApprovalError("approval state path must be a real directory")
    if os.name != "nt":
        path.chmod(0o700)


def action_digest(
    *,
    tool: str,
    action_kind: str,
    arguments: dict[str, Any],
    workspace: str,
    requester: str,
    policy_version: str = "default",
) -> str:
    """Return a stable digest binding every execution-relevant field."""
    if not requester or len(requester) > 128:
        raise ApprovalError("requester must contain 1 to 128 characters")
    if not tool or len(tool) > 128:
        raise ApprovalError("tool must contain 1 to 128 characters")
    if not policy_version or len(policy_version) > 128:
        raise ApprovalError("policy version must contain 1 to 128 characters")
    body = {
        "action_kind": action_kind,
        "arguments": arguments,
        "policy_version": policy_version,
        "requester": requester,
        "tool": tool,
        "workspace": str(Path(workspace).expanduser().resolve()),
    }
    try:
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ApprovalError("action arguments are not canonically serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    action_digest: str
    requester: str
    created_at: float
    expires_at: float
    status: str = "pending"
    approved_by: str = ""
    approved_at: float | None = None
    consumed_at: float | None = None
    mac: str = ""
    # Stamped server-side by the caller from a trusted adapter identity (see
    # mcp_server.py's evaluate_guard_action) -- never accepted from a model-
    # supplied argument. "unknown" only for records written before this field
    # existed. Lets ledger_access_policy grant or deny cross-adapter
    # visibility based on a value nothing but trusted adapter code could set.
    harness: str = "unknown"


class ApprovalStore:
    """Filesystem-backed approval store with atomic single-use consumption."""

    def __init__(self, state_dir: Path, *, now=time.time) -> None:
        self.state_dir = state_dir
        self.approvals_dir = state_dir / "codex-approvals"
        self.key_path = state_dir / "codex-approval.key"
        self._now = now

    def _key(self) -> bytes:
        _private_dir(self.state_dir)
        if not self.key_path.exists():
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(os.urandom(32))
        key = self.key_path.read_bytes()
        if len(key) != 32:
            raise ApprovalError("approval key is invalid")
        return key

    @staticmethod
    def _canonical(record: dict[str, Any]) -> bytes:
        body = {k: v for k, v in record.items() if k != "mac"}
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

    def _seal(self, record: dict[str, Any]) -> dict[str, Any]:
        record = dict(record)
        record["mac"] = hmac.new(
            self._key(), self._canonical(record), hashlib.sha256,
        ).hexdigest()
        return record

    def _verify(self, record: dict[str, Any]) -> None:
        expected = hmac.new(
            self._key(), self._canonical(record), hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, str(record.get("mac", ""))):
            raise ApprovalError("approval record authentication failed")

    def _path(self, approval_id: str) -> Path:
        if not approval_id or any(c not in "0123456789abcdef-" for c in approval_id):
            raise ApprovalError("invalid approval id")
        return self.approvals_dir / f"{approval_id}.json"

    def _write(self, path: Path, record: dict[str, Any]) -> None:
        _private_dir(self.state_dir)
        _private_dir(self.approvals_dir)
        tmp = path.with_suffix(f".{uuid4().hex}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._seal(record), stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def _read(self, approval_id: str) -> dict[str, Any]:
        path = self._path(approval_id)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ApprovalError("approval not found") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ApprovalError("approval record is unreadable") from exc
        self._verify(record)
        return record

    def get(self, approval_id: str) -> ApprovalRecord:
        """Read one record only after authenticating it."""
        return ApprovalRecord(**self._read(approval_id))

    def list_records(self) -> list[ApprovalRecord]:
        _private_dir(self.state_dir)
        _private_dir(self.approvals_dir)
        records = []
        for path in self.approvals_dir.glob("*.json"):
            try:
                records.append(self.get(path.stem))
            except ApprovalError:
                continue
        return sorted(records, key=lambda record: record.created_at, reverse=True)

    def list_visible(self, policy, *, harness: str, model: str) -> list[ApprovalRecord]:
        """Same visibility scoping as ReceiptChain.list_visible -- always
        includes `harness`'s own records, plus anything explicitly granted."""
        visible = policy.visible_harnesses(harness=harness, model=model)
        records = self.list_records()
        if visible == "*":
            return records
        return [r for r in records if r.harness in visible]

    def deny(self, approval_id: str, *, denied_by: str) -> ApprovalRecord:
        if not denied_by.strip():
            raise ApprovalError("operator identity is required")
        path = self._path(approval_id)
        record = self._read(approval_id)
        if record["status"] != "pending":
            raise ApprovalError("approval is not pending")
        record.update(status="denied", approved_by=denied_by.strip()[:128],
                      approved_at=self._now())
        self._write(path, record)
        return self.get(approval_id)

    def request(self, *, digest: str, requester: str, ttl_seconds: int = 300,
                harness: str = "unknown") -> ApprovalRecord:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ApprovalError("invalid action digest")
        if not requester or len(requester) > 128 or ttl_seconds < 1 or ttl_seconds > 3600:
            raise ApprovalError("requester and a TTL from 1 to 3600 seconds are required")
        now = self._now()
        record = ApprovalRecord(
            approval_id=str(uuid4()),
            action_digest=digest,
            requester=requester,
            created_at=now,
            expires_at=now + ttl_seconds,
            harness=harness[:64],
        )
        path = self._path(record.approval_id)
        self._write(path, asdict(record))
        return ApprovalRecord(**self._read(record.approval_id))

    def approve(
        self, approval_id: str, *, approved_by: str, expected_digest: str | None = None,
    ) -> ApprovalRecord:
        if not approved_by.strip():
            raise ApprovalError("operator identity is required")
        path = self._path(approval_id)
        record = self._read(approval_id)
        now = self._now()
        if record["status"] != "pending":
            raise ApprovalError("approval is not pending")
        if now > record["expires_at"]:
            raise ApprovalError("approval expired")
        if expected_digest is not None and not hmac.compare_digest(
            record["action_digest"], expected_digest,
        ):
            raise ApprovalError("approval digest does not match the displayed action")
        record.update(status="approved", approved_by=approved_by.strip()[:128], approved_at=now)
        self._write(path, record)
        return ApprovalRecord(**self._read(approval_id))

    def consume(self, approval_id: str, *, digest: str, requester: str) -> ApprovalRecord:
        path = self._path(approval_id)
        claim = path.with_suffix(".claim")
        _private_dir(self.state_dir)
        _private_dir(self.approvals_dir)
        try:
            claim_fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ApprovalError("approval is already being consumed or was used") from exc
        os.close(claim_fd)
        try:
            record = self._read(approval_id)
            now = self._now()
            if record["status"] != "approved":
                raise ApprovalError("approval has not been approved")
            if now > record["expires_at"]:
                raise ApprovalError("approval expired")
            if not hmac.compare_digest(record["action_digest"], digest):
                raise ApprovalError("action changed after approval")
            if not hmac.compare_digest(record["requester"], requester):
                raise ApprovalError("approval belongs to a different requester")
            record.update(status="consumed", consumed_at=now)
            self._write(path, record)
            return ApprovalRecord(**self._read(approval_id))
        except Exception:
            # A validation failure may be corrected before expiry. Successful
            # consumption leaves the claim marker as durable replay protection.
            try:
                consumed = self._read(approval_id).get("status") == "consumed"
            except ApprovalError:
                consumed = False
            if not consumed:
                claim.unlink(missing_ok=True)
            raise
