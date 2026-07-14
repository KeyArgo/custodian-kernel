"""NemoClaw sandbox adapter.

Wraps `nemohermes <sandbox> exec` so callers get a typed ExecResult and
typed exceptions instead of raw subprocess stdout/stderr. Before this
adapter existed, every failure mode collapsed into the same opaque text
blob regardless of cause — this distinguishes the ones that actually
require different handling:

  1. Sandbox gateway down (SandboxGatewayDownError) — a transport/connection
     failure reaching the sandbox itself. Recoverable (`nemohermes <sandbox>
     status` self-heals it); has nothing to do with the script being run.
  2. Timeout (SandboxTimeoutError) — the command didn't finish in time.
  3. Ordinary script failure — the sandbox was reachable, the script ran,
     and exited non-zero for its own reasons (bad input, a real bug). This
     is meaningful data, not an infrastructure failure, so `run()` returns
     it as a non-ok ExecResult by default rather than raising.

This is the reusable integration point other sites should import instead of
re-implementing subprocess/CLI-path logic — it replaces the inline
_nemohermes_bin()/_run_script() pair that used to live directly in
dashboard/api/operator.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from custodian.exceptions import (
    SandboxGatewayDownError,
    SandboxScriptError,
    SandboxTimeoutError,
)

# What nemohermes prints to stderr when it can't reach its own sandbox
# gateway. There's no distinct exit code for this case — a dead gateway and
# a failing script both just exit non-zero — so this is the only reliable
# signal to tell them apart. If nemohermes ever changes this wording, this
# adapter will stop catching the gateway-down case and it'll fall through
# to a generic non-ok ExecResult instead — not silently wrong, just less
# specific, so it's safe to leave un-pinned to a nemohermes version.
_GATEWAY_DOWN_SIGNATURE = "transport error"


@dataclass
class ExecResult:
    """Result of a command run inside the sandbox."""
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict:
        """Matches the shape the old _run_script() dict returned, so
        existing callers (e.g. dashboard/api/operator.py's jsonify(result))
        don't need to change their response shape during migration."""
        return {"returncode": self.returncode, "stdout": self.stdout, "stderr": self.stderr}


@dataclass
class DoctorCheck:
    group: str
    label: str
    status: str  # "ok" | "warn" | "fail" | "info"
    detail: str
    hint: Optional[str] = None


@dataclass
class SandboxHealth:
    """Parsed `nemohermes <sandbox> doctor --json` result."""
    sandbox: str
    status: str  # nemohermes's own overall verdict: "ok" | "warn" | "fail"
    failed: int
    warnings: int
    checks: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    @classmethod
    def from_doctor_json(cls, d: dict) -> "SandboxHealth":
        return cls(
            sandbox=d.get("sandbox", ""),
            status=d.get("status", "unknown"),
            failed=int(d.get("failed", 0)),
            warnings=int(d.get("warnings", 0)),
            checks=[DoctorCheck(**c) for c in d.get("checks", [])],
            raw=d,
        )


class NemoClawExecutor:
    """Adapter around `nemohermes <sandbox> exec` for running governed
    skill scripts inside a NemoClaw sandbox.

    Usage:
        from custodian.adapters.nemoclaw import NemoClawExecutor

        sandbox = NemoClawExecutor(sandbox_name="hermes-hackathon",
                                    fallback_binary_path="/home/argonaut/.local/bin/nemohermes")
        result = sandbox.run("earn.py", "--amount", "1200.00")
        if not result.ok:
            ...  # a real script failure, e.g. validation error — show it
    """

    def __init__(self, sandbox_name: str, binary_path: Optional[str] = None,
                 fallback_binary_path: Optional[str] = None,
                 default_timeout: float = 30):
        self.sandbox_name = sandbox_name
        self._binary_path = binary_path
        self._fallback_binary_path = fallback_binary_path
        self.default_timeout = default_timeout

    @property
    def binary_path(self) -> str:
        if self._binary_path:
            return self._binary_path
        found = shutil.which("nemohermes")
        if found:
            return found
        if self._fallback_binary_path:
            return self._fallback_binary_path
        raise SandboxGatewayDownError(
            "nemohermes binary not found on PATH and no fallback_binary_path configured"
        )

    def run(self, script_path: str, *args: str, timeout: Optional[float] = None,
            check: bool = False) -> ExecResult:
        """Run `python3 <script_path> *args` inside the sandbox.

        Raises SandboxGatewayDownError / SandboxTimeoutError for
        infrastructure failures. An ordinary non-zero exit from the script
        itself is returned as a non-ok ExecResult, not raised — unless
        check=True (mirrors subprocess.run's own check= semantics), in
        which case it's raised as SandboxScriptError.
        """
        cmd = [self.binary_path, self.sandbox_name, "exec", "--", "python3", script_path, *args]
        effective_timeout = timeout or self.default_timeout
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=effective_timeout)
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"sandbox '{self.sandbox_name}' exec timed out after {effective_timeout}s "
                f"running {script_path}"
            ) from e

        if proc.returncode != 0 and _GATEWAY_DOWN_SIGNATURE in proc.stderr:
            raise SandboxGatewayDownError(
                f"sandbox '{self.sandbox_name}' gateway unreachable — "
                f"run `nemohermes {self.sandbox_name} status` to self-heal.\n"
                f"raw stderr: {proc.stderr.strip()}"
            )

        result = ExecResult(returncode=proc.returncode,
                             stdout=proc.stdout.strip(), stderr=proc.stderr.strip())

        if check and not result.ok:
            raise SandboxScriptError(
                f"{script_path} exited {proc.returncode} inside sandbox '{self.sandbox_name}'\n"
                f"stderr: {result.stderr}"
            )

        return result

    def read_file(self, absolute_path: str, timeout: Optional[float] = None) -> Optional[str]:
        """Read a file's contents from inside the sandbox via `nemohermes
        exec -- cat`.

        Never read sandbox state through a host-side bind mount instead of
        this — this codebase has already been burned by that twice: once for
        staleness (a mount that lagged real writes by a sync interval and
        misreported a real spend as unverified — see the history in
        dashboard/scripts/agent_task_verified.py), and once for the mount
        not existing on the container at all (2026-07-14, this same adapter's
        introduction). `exec` is the only reliably-correct way to see current
        sandbox state from outside it.

        Returns None if the file doesn't exist (mirrors the
        Path.exists()-then-read_text() pattern every caller already used).
        Raises SandboxGatewayDownError if the sandbox itself is unreachable
        — distinct from an ordinary missing file.
        """
        cmd = [self.binary_path, self.sandbox_name, "exec", "--", "cat", absolute_path]
        effective_timeout = timeout or self.default_timeout
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=effective_timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"sandbox '{self.sandbox_name}' read_file timed out after "
                f"{effective_timeout}s reading {absolute_path}"
            ) from e

        if proc.returncode != 0:
            if _GATEWAY_DOWN_SIGNATURE in proc.stderr:
                raise SandboxGatewayDownError(
                    f"sandbox '{self.sandbox_name}' gateway unreachable — "
                    f"run `nemohermes {self.sandbox_name} status` to self-heal.\n"
                    f"raw stderr: {proc.stderr.strip()}"
                )
            # Anything else (No such file or directory, permission denied,
            # etc.) — treat as "no data available", matching how every
            # existing caller already handled a missing/unreadable file.
            return None
        return proc.stdout

    def write_file(self, absolute_path: str, content: str,
                    append: bool = False, timeout: Optional[float] = None) -> None:
        """Write `content` to a file inside the sandbox via `nemohermes exec
        -- sh -c 'cat > path'` (or `>>` if append=True), piping content over
        stdin. Not atomic on its own — callers writing state that must never
        be seen half-written (e.g. authority.json) should write to a temp
        path and `move_file` it into place, mirroring notify.py's own
        _atomic_write pattern."""
        redirect = '>>' if append else '>'
        cmd = [self.binary_path, self.sandbox_name, "exec", "--",
               "sh", "-c", f'cat {redirect} "$1"', "_", absolute_path]
        effective_timeout = timeout or self.default_timeout
        try:
            proc = subprocess.run(cmd, input=content, capture_output=True, text=True,
                                   timeout=effective_timeout)
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"sandbox '{self.sandbox_name}' write_file timed out after "
                f"{effective_timeout}s writing {absolute_path}"
            ) from e
        if proc.returncode != 0:
            if _GATEWAY_DOWN_SIGNATURE in proc.stderr:
                raise SandboxGatewayDownError(
                    f"sandbox '{self.sandbox_name}' gateway unreachable — "
                    f"run `nemohermes {self.sandbox_name} status` to self-heal.\n"
                    f"raw stderr: {proc.stderr.strip()}"
                )
            raise SandboxScriptError(f"write to {absolute_path} failed: {proc.stderr.strip()}")

    def delete_file(self, absolute_path: str, timeout: Optional[float] = None) -> None:
        """Delete a file inside the sandbox via `nemohermes exec -- rm -f`.
        rm -f never errors on a missing file, so this is safe to call
        whether or not the file currently exists."""
        cmd = [self.binary_path, self.sandbox_name, "exec", "--", "rm", "-f", absolute_path]
        self._run_fs_command(cmd, timeout, f"delete {absolute_path}")

    def move_file(self, src_absolute_path: str, dst_absolute_path: str,
                  timeout: Optional[float] = None) -> None:
        """Rename/move a file inside the sandbox via `nemohermes exec -- mv`."""
        cmd = [self.binary_path, self.sandbox_name, "exec", "--", "mv",
               src_absolute_path, dst_absolute_path]
        self._run_fs_command(cmd, timeout, f"move {src_absolute_path} -> {dst_absolute_path}")

    def _run_fs_command(self, cmd: list, timeout: Optional[float], description: str) -> None:
        effective_timeout = timeout or self.default_timeout
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=effective_timeout)
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"sandbox '{self.sandbox_name}' timed out after {effective_timeout}s: {description}"
            ) from e
        if proc.returncode != 0:
            if _GATEWAY_DOWN_SIGNATURE in proc.stderr:
                raise SandboxGatewayDownError(
                    f"sandbox '{self.sandbox_name}' gateway unreachable — "
                    f"run `nemohermes {self.sandbox_name} status` to self-heal.\n"
                    f"raw stderr: {proc.stderr.strip()}"
                )
            raise SandboxScriptError(f"{description} failed: {proc.stderr.strip()}")

    def doctor(self, timeout: float = 15) -> SandboxHealth:
        """Wraps `nemohermes <sandbox> doctor --json`. Exit code reflects
        overall health (non-zero if anything failed) so it's ignored here —
        the JSON payload on stdout is the real signal."""
        cmd = [self.binary_path, self.sandbox_name, "doctor", "--json"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"sandbox '{self.sandbox_name}' doctor timed out after {timeout}s"
            ) from e
        try:
            return SandboxHealth.from_doctor_json(json.loads(proc.stdout))
        except (json.JSONDecodeError, TypeError) as e:
            raise SandboxGatewayDownError(
                f"sandbox '{self.sandbox_name}' doctor produced no parseable JSON — "
                f"gateway likely unreachable.\nraw stdout: {proc.stdout!r}\nraw stderr: {proc.stderr!r}"
            ) from e
