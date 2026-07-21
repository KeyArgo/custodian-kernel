"""Filesystem/exec confinement for governed skill scripts.

Wraps a skill's ``execute.py`` subprocess in a bwrap (bubblewrap) sandbox:
a fresh PID/UTS/IPC/cgroup namespace, the whole filesystem re-mounted
read-only, and explicit read-write binds for only the directories the
tool actually needs (its own state dir, its own skill dir). Sensitive
host directories (SSH keys, cloud credentials, the Paladin vault) are
masked to an empty tmpfs even though the read-only bind would already
block writes to them -- masking also blocks *reading* them, which matters
because this layer deliberately does not isolate the network (most
skills need it to do their job), so a compromised script could otherwise
still read a secret and phone it out.

This is independent of paladin/sandbox.py, which solves a different
problem (network-isolated egress with a gateway-socket credential model)
for a different caller (paladin's own CLI). custodian/ must never import
paladin/ (see tests/test_architecture_boundaries.py) -- the two modules
share an approach, not code.

Threat model, stated plainly: this stops a compromised or buggy skill
script from reading/writing arbitrary host paths outside its declared
working area, and from seeing or signaling other processes on the host.
It does NOT stop network exfiltration (network namespace is shared) and
it does NOT stop a skill from misusing whatever it's allowed to read or
write within its own rw-bound directories -- that's kernel_self_protection.py
and the other adapters' job, at the argument level, before invoke() ever
gets here.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence

from custodian.exceptions import ToolSandboxUnavailableError

# Sensitive directories masked to an empty tmpfs regardless of the tool's
# declared needs -- read access to these would let a compromised script
# exfiltrate credentials over the (deliberately unconfined) network.
_DEFAULT_MASK_DIRS = (
    "~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gcloud", "~/.paladin",
)


def bwrap_path() -> Optional[str]:
    return shutil.which("bwrap")


@functools.lru_cache(maxsize=1)
def sandbox_available() -> bool:
    """True iff bwrap is present and unprivileged user namespaces work
    with the exact flag set this module uses. Cached -- the answer
    doesn't change within a process."""
    bw = bwrap_path()
    if not bw:
        return False
    try:
        r = subprocess.run(
            [bw, "--unshare-user", "--unshare-pid", "--unshare-uts",
             "--unshare-ipc", "--unshare-cgroup", "--die-with-parent",
             "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
             "--", "/bin/true"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _existing_dirs(paths: Sequence[str]) -> list[str]:
    seen = set()
    out = []
    for p in paths:
        resolved = str(Path(p).expanduser())
        if resolved not in seen and os.path.isdir(resolved):
            seen.add(resolved)
            out.append(resolved)
    return out


def build_sandboxed_argv(cmd: Sequence[str], *, rw_dirs: Sequence[str] = (),
                         mask_dirs: Sequence[str] = _DEFAULT_MASK_DIRS) -> list[str]:
    """Build the bwrap argv wrapping ``cmd``.

    ``rw_dirs`` are bound read-write, in order, after the read-only base
    bind and the tmpfs masks -- later binds win, so an rw_dir that is
    itself inside a masked directory (shouldn't happen in practice, but
    cheap to get right) still ends up writable.
    """
    bw = bwrap_path()
    argv = [
        bw,
        "--unshare-user", "--unshare-pid", "--unshare-uts",
        "--unshare-ipc", "--unshare-cgroup",
        "--die-with-parent",
        "--new-session",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
    ]
    for d in _existing_dirs(mask_dirs):
        argv += ["--tmpfs", d]
    for d in _existing_dirs(rw_dirs):
        argv += ["--bind", d, d]
    argv += ["--"]
    argv += list(cmd)
    return argv


def require_sandboxed_argv(cmd: Sequence[str], *, rw_dirs: Sequence[str] = (),
                           allow_unsandboxed: bool = False) -> list[str]:
    """Return the argv to actually execute: bwrap-wrapped if a sandbox can
    be built, or the bare ``cmd`` if none can and the caller opted in via
    ``allow_unsandboxed``.

    Raises ToolSandboxUnavailableError otherwise -- fail closed rather than
    run a governed script with full ambient filesystem access.
    """
    if sandbox_available():
        return build_sandboxed_argv(cmd, rw_dirs=rw_dirs)
    if allow_unsandboxed:
        return list(cmd)
    raise ToolSandboxUnavailableError(
        "cannot build a filesystem/exec-isolated sandbox for this skill "
        "(bwrap missing or unprivileged user namespaces disabled). Install "
        "bubblewrap / enable unprivileged user namespaces, or set "
        "CUSTODIAN_ALLOW_UNSANDBOXED_TOOLS=1 to run governed skill scripts "
        "without filesystem confinement (not recommended)."
    )
