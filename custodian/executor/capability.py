"""Signed, single-use, digest-bound capabilities for the delegated executor.

A capability is what closes the gap between "the kernel escalated this
action" and "a human actually approved *this exact* action." Without it, an
approval is just a boolean a compromised agent process could apply to any
action it liked ("the operator said yes" to *something*, replayed against a
different, more dangerous request). Binding every execution-relevant field
into a digest, sealing the record with an HMAC key the agent never holds,
and consuming it exactly once closes all three of those gaps at once.

Same design shape as custodian.codex_guard.approvals (action-bound,
HMAC-sealed, atomic single-use consumption via an O_EXCL claim file) --
independently implemented here because custodian/ must never import
codex_guard's integration-specific code (this module serves the general
tool registry, not one MCP integration), not because the underlying
technique should differ.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import platform
from pathlib import Path
import time
from typing import Any, Optional
from uuid import uuid4

from custodian.exceptions import CustodianError




def _ensure_private_permissions(dir_path: Path, file_path: Path) -> None:
    """Enforce 0700 on *dir_path* and 0600 on *file_path*, cross-platform.

    On Windows (where chmod is limited), we at least skip silently since the
    OS security model replaces Unix permissions there.
    """
    try:
        os.chmod(dir_path, 0o700)
    except OSError:
        if platform.system() != "Windows":
            raise
    if file_path.exists():
        try:
            os.chmod(file_path, 0o600)
        except OSError:
            if platform.system() != "Windows":
                raise


class CapabilityError(CustodianError):
    """A capability is missing, invalid, expired, changed, or already used."""

    def __init__(self, message: str = "capability error") -> None:
        super().__init__(message)


def _path_is_symlink_in_chain(path: Path) -> bool:
    """Return True if the path itself or any parent component is a symlink.

    Inspects the *unresolved* path chain so that a symlink at *any* level --
    including a directory component in the middle of the path -- is caught.
    """
    for part in [path] + list(path.parents):
        try:
            if part.is_symlink():
                return True
        except OSError:
            pass
    return False


def action_digest(*, tool: str, args: dict, workspace: str, requester: str,
                  policy_version: str = "default") -> str:
    """Return a stable digest binding every execution-relevant field.

    Two proposals for the "same" tool with different args, a different
    workspace, or a different requester must never collide on one digest --
    that would let an approval for one action be consumed by another.
    """
    body = {
        "tool": tool,
        "args": args,
        "workspace": str(Path(workspace).expanduser().resolve()) if workspace else "",
        "requester": requester,
        "policy_version": policy_version,
    }
    try:
        encoded = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CapabilityError("action is not canonically serializable") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    action_digest: str
    requester: str
    created_at: float
    expires_at: float
    status: str = "pending"     # pending -> approved -> consumed
    approved_by: str = ""
    approved_at: Optional[float] = None
    consumed_at: Optional[float] = None
    mac: str = ""

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_consumed(self) -> bool:
        return self.status == "consumed"

    def is_expired(self, *, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) > self.expires_at


class CapabilityStore:
    """Filesystem-backed capability store with atomic single-use consumption.

    Runs inside the executor process only -- the signing key lives at
    ``state_dir/executor-capability.key`` (mode 0600) and is never read by
    custodian.executor.client or by CustodianTool.invoke()'s agent-side
    code. An agent process can see a capability's public fields (it has to,
    to know its capability_id) but cannot forge or alter a sealed record
    without the key: any tampering fails ``_verify()``.
    """

    def __init__(self, state_dir: Path, *, now=time.time) -> None:
        self.state_dir = state_dir
        self.capabilities_dir = state_dir / "executor-capabilities"
        self.key_path = state_dir / "executor-capability.key"
        self._now = now

    def _key(self) -> bytes:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _ensure_private_permissions(self.state_dir, self.key_path)
        if _path_is_symlink_in_chain(self.key_path):
            raise CapabilityError("executor capability key path compromised")
        if not self.key_path.exists():
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(os.urandom(32))
        _ensure_private_permissions(self.state_dir, self.key_path)
        try:
            fd = os.open(self.key_path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise CapabilityError("executor capability key is unreadable") from exc
        try:
            key = os.read(fd, 64)
        finally:
            os.close(fd)
        if len(key) != 32:
            raise CapabilityError("executor capability key is invalid")
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
            raise CapabilityError("capability record authentication failed")

    def _path(self, capability_id: str) -> Path:
        if not capability_id or any(c not in "0123456789abcdef-" for c in capability_id):
            raise CapabilityError("invalid capability id")
        path = self.capabilities_dir / f"{capability_id}.json"
        if _path_is_symlink_in_chain(path):
            raise CapabilityError("capability path contains symlink")
        return path

    def _write(self, path: Path, record: dict[str, Any]) -> None:
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)
        _ensure_private_permissions(self.capabilities_dir, path)
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

    def _read(self, capability_id: str) -> dict[str, Any]:
        path = self._path(capability_id)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise CapabilityError("capability record is unreadable") from exc
        try:
            raw = os.read(fd, 131072)
        finally:
            os.close(fd)
        try:
            record = json.loads(raw.decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CapabilityError("capability record is unreadable") from exc
        self._verify(record)
        return record

    def request(self, *, digest: str, requester: str, ttl_seconds: int = 600) -> CapabilityRecord:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise CapabilityError("invalid action digest")
        if not requester or ttl_seconds < 1 or ttl_seconds > 3600:
            raise CapabilityError("requester and a TTL from 1 to 3600 seconds are required")
        now = self._now()
        record = CapabilityRecord(
            capability_id=str(uuid4()),
            action_digest=digest,
            requester=requester[:128],
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        path = self._path(record.capability_id)
        self._write(path, asdict(record))
        return CapabilityRecord(**self._read(record.capability_id))

    def _require_no_symlinks(self) -> None:
        if _path_is_symlink_in_chain(self.capabilities_dir):
            raise CapabilityError("capability storage is compromised")

    def find_pending_by_digest(self, digest: str, requester: str) -> Optional[CapabilityRecord]:
        """Return the most recent non-expired pending/approved capability
        for this exact (digest, requester) pair, if any -- lets a caller
        that just retries the same proposal (rather than remembering a
        capability_id) discover its own outstanding or approved request."""
        self._require_no_symlinks()
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)
        now = self._now()
        best: Optional[CapabilityRecord] = None
        for entry in self.capabilities_dir.glob("*.json"):
            capability_id = entry.stem
            try:
                record = CapabilityRecord(**self._read(capability_id))
            except CapabilityError:
                continue
            if record.action_digest != digest or record.requester != requester:
                continue
            # "denied" must be excluded too, not just "consumed" -- the
            # docstring above promises "pending/approved" only. Without
            # this, a resend of the identical proposal after an operator's
            # explicit denial kept resolving to that same, permanently
            # denied capability_id (approve() on it fails with "capability
            # is not pending" forever) instead of getting a fresh one --
            # the exact action could never be re-escalated again until its
            # original TTL lapsed.
            if record.status in ("consumed", "denied") or record.is_expired(now=now):
                continue
            if best is None or record.created_at > best.created_at:
                best = record
        return best

    def approve(self, capability_id: str, *, approved_by: str,
                expected_digest: str | None = None) -> CapabilityRecord:
        if not approved_by.strip():
            raise CapabilityError("operator identity is required")
        path = self._path(capability_id)
        record = self._read(capability_id)
        now = self._now()
        if record["status"] != "pending":
            raise CapabilityError("capability is not pending")
        if now > record["expires_at"]:
            raise CapabilityError("capability expired")
        if expected_digest is not None and not hmac.compare_digest(
            str(record["action_digest"]), expected_digest
        ):
            raise CapabilityError("displayed action digest does not match capability")
        record.update(status="approved", approved_by=approved_by.strip()[:128], approved_at=now)
        self._write(path, record)
        return CapabilityRecord(**self._read(capability_id))

    def deny(self, capability_id: str, *, denied_by: str) -> CapabilityRecord:
        if not denied_by.strip():
            raise CapabilityError("operator identity is required")
        path = self._path(capability_id)
        record = self._read(capability_id)
        if record["status"] != "pending":
            raise CapabilityError("capability is not pending")
        record.update(status="denied", approved_by=denied_by.strip()[:128],
                      approved_at=self._now())
        self._write(path, record)
        return CapabilityRecord(**self._read(capability_id))

    def get(self, capability_id: str) -> CapabilityRecord:
        """Read one record only after authenticating it."""
        return CapabilityRecord(**self._read(capability_id))

    def list_records(self) -> list[CapabilityRecord]:
        self._require_no_symlinks()
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for entry in self.capabilities_dir.glob("*.json"):
            try:
                records.append(CapabilityRecord(**self._read(entry.stem)))
            except CapabilityError:
                continue
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def consume(self, capability_id: str, *, digest: str, requester: str) -> CapabilityRecord:
        """Atomically mark a capability consumed. Safe under concurrent
        callers: the O_EXCL claim file means exactly one caller wins the
        race to consume any given capability_id."""
        path = self._path(capability_id)
        claim = path.with_suffix(".claim")
        self.capabilities_dir.mkdir(parents=True, exist_ok=True)
        try:
            claim_fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise CapabilityError("capability is already being consumed or was used") from exc
        os.close(claim_fd)
        try:
            record = self._read(capability_id)
            now = self._now()
            if record["status"] != "approved":
                raise CapabilityError("capability has not been approved")
            if now > record["expires_at"]:
                raise CapabilityError("capability expired")
            if not hmac.compare_digest(record["action_digest"], digest):
                raise CapabilityError("action changed after approval")
            if not hmac.compare_digest(record["requester"], requester):
                raise CapabilityError("capability belongs to a different requester")
            record.update(status="consumed", consumed_at=now)
            self._write(path, record)
            return CapabilityRecord(**self._read(capability_id))
        finally:
            if claim.exists():
                claim.unlink(missing_ok=True)
