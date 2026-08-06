"""Network-isolated sandboxed egress: run a command that can reach *nothing*
except the Paladin egress gateway.

The child runs under ``bwrap`` (bubblewrap) with ``--unshare-all`` — a fresh
user/pid/net/ipc/uts/cgroup namespace. With the network namespace unshared
the child has no route to anywhere; the single hole is a Unix socket bound
into the sandbox, over which it speaks to :class:`paladin.egress.EgressGateway`.
The credential is attached on the host side and never enters the child.

Two non-obvious things this module gets right, because getting them wrong
would hand the child the very secrets we protect:

1. **The vault is masked.** A blanket ``--ro-bind / /`` would expose
   ``~/.paladin/vault.key`` (and ``~/.ssh`` etc.) read-only to the child,
   which could then decrypt the vault itself and skip the broker entirely.
   We overlay a tmpfs on the vault home, the keyfile's directory, and a
   default denylist so those paths read empty inside the sandbox.
2. **The environment is rebuilt, not inherited.** The parent may hold
   ``PALADIN_PASSPHRASE`` / ``PALADIN_KEYFILE`` (and arbitrary other
   secrets) in its own environment. The child is given a fresh minimal env
   — PATH/HOME/LANG plus the gateway's socket/token/refs vars — so nothing
   leaks in through inherited environment.

Fail-closed: if bwrap or unprivileged user namespaces are unavailable, this
raises :class:`SandboxUnavailableError` rather than silently running the
child unconfined. ``allow_unsandboxed=True`` opts into a **deprecated**
degraded mode that still routes secrets only through the gateway (never into
the child's env) but does NOT network-isolate the child.

**Deprecation (security beta):** unsandboxed egress execution is deprecated
and will be removed in a future release.  Setting ``allow_unsandboxed=True``
now prints a prominent stderr banner; to acknowledge the risk and suppress
the banner, set ``PALADIN_UNSAFE_ACKNOWLEDGED=1`` in the environment.
Migrate to ``paladin exec --sandbox`` for full network isolation.
"""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Optional, Sequence

from paladin.broker import Broker, DEFAULT_EGRESS_TIMEOUT
from paladin.egress import EgressGateway
from paladin.errors import SandboxUnavailableError

# Directories masked (tmpfs-overlaid to read empty) inside the sandbox even
# though the base is a read-only bind of /. The vault home and keyfile dir
# are added dynamically on top of this.  .kube and .docker were added after
# the containment watchdog (sandbox-audit) flagged them: on hosts where they
# exist, kubeconfig and docker registry credentials would otherwise be
# visible read-only to the egress child.
DEFAULT_MASK_DIRS = ("~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gcloud",
                     "~/.kube", "~/.docker",
                     "~/.custodian", "~/.talaria")

# Container-runtime sockets that must never be visible to the egress child:
# a reachable docker/podman socket would let it drive the host container
# runtime. These are FILES, so they are masked by binding /dev/null over the
# path (connect() then fails with ENOTSOCK). The containment watchdog
# recognizes /dev/null-over-deny-path binds as masks.
DEFAULT_MASK_SOCKETS = (
    "/var/run/docker.sock",
    "/run/docker.sock",
    "/run/podman/podman.sock",
)

# ---------------------------------------------------------------------------
# Deprecation of unsandboxed execution paths
# ---------------------------------------------------------------------------

UNSAFE_ACKNOWLEDGEMENT_ENV = "PALADIN_UNSAFE_ACKNOWLEDGED"

_UNSAFE_DEPRECATION_BANNER = (
    "╔══════════════════════════════════════════════════════════════════════════╗\n"
    "║  DEPRECATED: unsandboxed egress execution                              ║\n"
    "║                                                                         ║\n"
    "║  Running a Paladin child WITHOUT network isolation is deprecated.       ║\n"
    "║  The child can see your network and operating environment even though   ║\n"
    "║  secrets stay out of its env.  Migrate to `paladin exec --sandbox` to  ║\n"
    "║  get full network isolation (the child sees nothing but the Paladin    ║\n"
    "║  egress gateway).                                                      ║\n"
    "║                                                                         ║\n"
    "║  This degraded path will be removed in a future release.                ║\n"
    "║  Set %s=1 to acknowledge and suppress this banner.                      ║\n"
    "╚══════════════════════════════════════════════════════════════════════════╝"
) % UNSAFE_ACKNOWLEDGEMENT_ENV


def unsafe_acknowledged() -> bool:
    """True when the operator has explicitly acknowledged the risks of
    unsandboxed execution by setting ``PALADIN_UNSAFE_ACKNOWLEDGED=1``."""
    return os.environ.get(UNSAFE_ACKNOWLEDGEMENT_ENV) == "1"


def _warn_unsafe_deprecated(caller: str = "") -> None:
    """Print the unsandboxed-deprecation banner to stderr, unless the
    operator has set the acknowledgement env var."""
    if not unsafe_acknowledged():
        print(f"\n[paladin] {caller}:", file=sys.stderr)
        print(_UNSAFE_DEPRECATION_BANNER, file=sys.stderr)
        sys.stderr.flush()


# ---------------------------------------------------------------------------


def bwrap_path() -> Optional[str]:
    return shutil.which("bwrap")


@functools.lru_cache(maxsize=1)
def sandbox_available() -> bool:
    """True iff a real ``--unshare-all`` sandbox can be built here (bwrap
    present AND unprivileged user namespaces usable). Cached — the answer
    doesn't change within a process."""
    bw = bwrap_path()
    if not bw:
        return False
    try:
        r = subprocess.run(
            [bw, "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev",
             "--die-with-parent", "true"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _mask_dirs(vault_home: Path) -> list[str]:
    dirs = set()
    for d in DEFAULT_MASK_DIRS:
        dirs.add(str(Path(d).expanduser()))
    dirs.add(str(vault_home))
    keyfile = os.environ.get("PALADIN_KEYFILE")
    if keyfile:
        dirs.add(str(Path(keyfile).expanduser().parent))
    return [d for d in sorted(dirs) if os.path.isdir(d)]


def _child_base_env(extra: dict) -> dict:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    env.update(extra)
    return env


def build_bwrap_argv(sock_dir: Path, cmd: Sequence[str],
                     vault_home: Path) -> list[str]:
    bw = bwrap_path()
    argv = [
        bw,
        "--unshare-all",          # user, ipc, pid, net, uts, cgroup
        "--die-with-parent",
        "--ro-bind", "/", "/",    # base: whole fs read-only...
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
    ]
    for d in _mask_dirs(vault_home):
        argv += ["--tmpfs", d]    # ...with the crown jewels masked to empty
    argv += _socket_mask_argv(DEFAULT_MASK_SOCKETS)
    # The one hole: the UDS. A read-only bind is enough to connect() (verified);
    # the child cannot drop files in the dir or unlink the socket.
    argv += ["--ro-bind", str(sock_dir), str(sock_dir)]
    argv += list(cmd)
    return argv


def _socket_mask_argv(sockets: Sequence[str]) -> list[str]:
    """Bind /dev/null over container-runtime sockets that exist on the host."""
    argv: list[str] = []
    for s in sockets:
        if os.path.exists(s):
            argv += ["--ro-bind", "/dev/null", s]
    return argv


def spawn_sandboxed(cmd: Sequence[str], broker: Broker, requester: str,
                    band: str = "L0", allow_refs: Optional[set] = None,
                    timeout: float = DEFAULT_EGRESS_TIMEOUT,
                    capture_output: bool = True,
                    allow_unsandboxed: bool = False,
                    extra_env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """Run ``cmd`` with an egress gateway but NO plaintext secrets in its
    environment. The child uses ``paladin.egress_client`` to make
    authenticated calls; the credential is attached host-side by ``broker``.

    Under a real sandbox the child also has no network at all except the
    gateway socket. Raises :class:`SandboxUnavailableError` if that can't be
    built and ``allow_unsandboxed`` is False.

    ``allow_unsandboxed=True`` is **deprecated** — it opts into a degraded path
    where secrets stay out of the child env but the child is not network-confined.
    Migrate to ``paladin exec --sandbox`` instead.  Set
    ``PALADIN_UNSAFE_ACKNOWLEDGED=1`` to acknowledge and suppress the
    deprecation banner.
    """
    sandboxed = sandbox_available()
    if not sandboxed and not allow_unsandboxed:
        raise SandboxUnavailableError(
            "cannot build a network-isolated egress sandbox here "
            "(bwrap missing or unprivileged user namespaces disabled). "
            "Install bubblewrap / enable userns to use the sandbox, or "
            "pass allow_unsandboxed=True to run the child without network "
            "isolation (deprecated — see the paladin sandbox docs)."
        )

    vault_home = Path(broker.vault.path).parent
    gw = EgressGateway(broker, requester=requester, band=band,
                       allow_refs=allow_refs, timeout=timeout)
    gw.start()
    try:
        child_env = _child_base_env({**gw.child_env(), **(extra_env or {})})
        if sandboxed:
            sock_dir = Path(gw.socket_path).parent
            argv = build_bwrap_argv(sock_dir, cmd, vault_home)
        else:
            _warn_unsafe_deprecated("spawn_sandboxed(allow_unsandboxed=True)")
            warnings.warn(
                "paladin: running egress child WITHOUT network isolation "
                "(sandbox unavailable, allow_unsandboxed=True). Secrets stay "
                "out of the child env, but it is not network-confined — this "
                "mode is deprecated and will be removed in a future release.",
                RuntimeWarning, stacklevel=2,
            )
            argv = list(cmd)
        return subprocess.run(
            argv, env=child_env, timeout=timeout,
            capture_output=capture_output, text=True, shell=False,
        )
    finally:
        gw.stop()
