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

# A confined run intentionally exposes a much smaller host surface than the
# backwards-compatible sandbox above.  In particular it does not ro-bind `/`:
# a read-only bind still lets a compromised child read every host secret that
# its parent can read unless each sensitive directory is remembered and
# overlaid.  These are the runtime directories a normal Python tool needs.
_CONFINED_RO_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/libx32", "/etc")

# ``--proc`` creates a new procfs mount, but a few proc nodes expose global
# kernel state or are unexpectedly powerful on older kernels.  Keep the
# ordinary per-namespace proc view useful for tools while making these nodes
# inert.  ``--ro-bind-try`` also keeps the profile portable across kernels
# whose proc layout differs.
_CONFINED_PROC_READONLY = ("/proc/sys",)
_CONFINED_PROC_MASKS = (
    "/proc/sysrq-trigger", "/proc/kcore", "/proc/kallsyms", "/proc/keys",
    "/proc/timer_list", "/proc/sched_debug",
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


@functools.lru_cache(maxsize=1)
def confined_sandbox_available() -> bool:
    """True only when the stricter no-network profile can start.

    A host can allow the legacy mount namespace but reject network namespaces.
    Confined mode must test the boundary it actually promises rather than
    silently discovering the difference after a tool has been authorized.
    """
    bw = bwrap_path()
    if not bw:
        return False
    try:
        result = subprocess.run(
            [bw, "--unshare-user", "--unshare-pid", "--unshare-uts",
             "--unshare-ipc", "--unshare-cgroup", "--unshare-net",
             "--die-with-parent", "--ro-bind", "/", "/", "--dev", "/dev",
             "--proc", "/proc", "--clearenv", "--", "/bin/true"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
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


def _confined_workspace(workspace: str) -> str:
    """Validate the sole write capability for a confined child.

    A broad workspace turns a mount boundary into a no-op.  This is kept here
    rather than in a CLI caller so every future confined execution path shares
    the same fail-closed check.
    """
    if not workspace:
        raise ToolSandboxUnavailableError(
            "confined execution requires CUSTODIAN_CONFINED_WORKSPACE"
        )
    path = Path(workspace).expanduser().resolve()
    if not path.is_dir() or path == path.parent or path == Path.home().resolve():
        raise ToolSandboxUnavailableError(
            "confined workspace must be an existing project directory, not / or the home directory"
        )
    return str(path)


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


def build_confined_argv(
    cmd: Sequence[str], *, workspace: str, ro_dirs: Sequence[str] = (),
) -> list[str]:
    """Build Custodian's strict, no-network Bubblewrap profile.

    The child receives only a minimal read-only runtime, explicitly supplied
    skill code, and one declared read-write workspace.  It inherits neither
    the host network nor the parent environment.  This is opt-in because
    networked and ambient-credential tools must be redesigned around an egress
    broker before they can run safely in this profile.
    """
    root = _confined_workspace(workspace)
    bw = bwrap_path()
    if not bw:
        raise ToolSandboxUnavailableError("bubblewrap is not installed")
    argv = [
        bw,
        "--unshare-user", "--unshare-pid", "--unshare-uts",
        "--unshare-ipc", "--unshare-cgroup", "--unshare-net",
        "--die-with-parent", "--new-session",
    ]
    for directory in _existing_dirs(_CONFINED_RO_DIRS):
        argv += ["--ro-bind", directory, directory]
    for directory in _existing_dirs(ro_dirs):
        resolved = str(Path(directory).expanduser().resolve())
        if resolved != root:
            argv += ["--ro-bind", resolved, resolved]
    argv += ["--tmpfs", "/tmp", "--dev", "/dev", "--proc", "/proc"]
    for proc_dir in _CONFINED_PROC_READONLY:
        argv += ["--ro-bind-try", proc_dir, proc_dir]
    # bwrap cannot create an arbitrary absent node inside a procfs mount. Mask
    # only nodes that exist on this kernel; the reduced procfs still omits the
    # rest, and this keeps the profile portable across proc layouts.
    for proc_node in _CONFINED_PROC_MASKS:
        if Path(proc_node).exists():
            argv += ["--ro-bind-try", "/dev/null", proc_node]
    argv += ["--bind", root, root, "--clearenv"]
    argv += ["--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"]
    argv += ["--chdir", root, "--"]
    argv += list(cmd)
    return argv


def require_confined_argv(
    cmd: Sequence[str], *, workspace: str, ro_dirs: Sequence[str] = (),
) -> list[str]:
    """Return a strict sandbox argv or fail closed.

    Unlike :func:`require_sandboxed_argv`, confined execution deliberately has
    no environment-variable escape hatch for an unsandboxed fallback.
    """
    if not confined_sandbox_available():
        raise ToolSandboxUnavailableError(
            "cannot build a confined execution sandbox (bubblewrap missing or user namespaces disabled)"
        )
    return build_confined_argv(cmd, workspace=workspace, ro_dirs=ro_dirs)


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
