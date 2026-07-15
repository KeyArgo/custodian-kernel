"""Paladin → NemoClaw egress: secrets into a sandbox exec, leaving no trace.

Runs a script inside a NemoClaw sandbox with Paladin-resolved secrets in
its environment, subject to three hard rules:

1. **Never on the command line.** argv is visible to `ps` and shell
   history on the sandbox host; secrets ride stdin instead.
2. **Never on sandbox disk.** No env file is written inside (or outside)
   the sandbox; the child sources its environment from the stdin pipe.
3. **Grant-gated per sandbox.** Resolution uses requester
   ``sandbox:<name>``, so a vault grant must explicitly name the sandbox
   before any secret crosses into it — and the audit chain records it.

The transport mirrors NemoClawExecutor's command construction (same
binary discovery, same gateway-down detection) but pipes an env block
over stdin: ``sh -c 'set -a; . /dev/stdin; set +a; exec python3 ...'``.
"""
from __future__ import annotations

import shlex
import subprocess
from typing import Mapping, Optional, Sequence

from custodian.adapters.nemoclaw import (
    ExecResult,
    NemoClawExecutor,
    _GATEWAY_DOWN_SIGNATURE,
)
from custodian.exceptions import SandboxGatewayDownError, SandboxTimeoutError


def _env_block(env: Mapping[str, str]) -> str:
    """Render KEY='value' lines safe to `.`-source in a POSIX shell."""
    lines = []
    for key, value in env.items():
        if not key.replace("_", "").isalnum():
            raise ValueError(f"unsafe env var name {key!r}")
        lines.append(f"{key}={shlex.quote(value)}")
    return "\n".join(lines) + "\n"


def governed_sandbox_exec(
    executor: NemoClawExecutor,
    broker,
    refs: Mapping[str, object],   # {ENV_VAR: SecretRef | "paladin://name"}
    script_path: str,
    *args: str,
    band: str = "L1",
    timeout: Optional[float] = None,
) -> ExecResult:
    """Run `python3 script_path *args` in the sandbox with secrets injected.

    `broker` is a paladin.Broker; every ref resolves under requester
    ``sandbox:<sandbox_name>`` (grant-gated + audited). Raises
    GrantDeniedError before anything touches the sandbox if any ref is
    not granted.
    """
    requester = f"sandbox:{executor.sandbox_name}"
    env = broker.build_env(refs, requester=requester, band=band, base_env={})

    inner = "set -a; . /dev/stdin; set +a; exec python3 " + " ".join(
        shlex.quote(p) for p in (script_path, *args)
    )
    cmd = [executor.binary_path, executor.sandbox_name, "exec", "--",
           "sh", "-c", inner]
    effective_timeout = timeout or executor.default_timeout
    try:
        proc = subprocess.run(
            cmd, input=_env_block(env), capture_output=True, text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxTimeoutError(
            f"sandbox '{executor.sandbox_name}' governed exec timed out after "
            f"{effective_timeout}s running {script_path}"
        ) from e
    finally:
        env.clear()  # drop plaintext references promptly

    if proc.returncode != 0 and _GATEWAY_DOWN_SIGNATURE in proc.stderr:
        raise SandboxGatewayDownError(
            f"sandbox '{executor.sandbox_name}' gateway unreachable — "
            f"run `nemohermes {executor.sandbox_name} status` to self-heal.\n"
            f"raw stderr: {proc.stderr.strip()}"
        )
    return ExecResult(returncode=proc.returncode,
                      stdout=proc.stdout.strip(), stderr=proc.stderr.strip())
