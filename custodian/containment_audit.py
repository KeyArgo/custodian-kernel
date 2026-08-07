"""Containment leak watchdog: find sensitive host paths a sandbox would expose.

The security property of every confined execution boundary (Bubblewrap
launchers, the Paladin egress sandbox, any future Rust/VM confinement) is the
same: paths holding credentials, the credential vault, and the governance
evidence chain must be invisible inside the sandbox.  This module checks that
property three independent ways:

1. ``audit_mount_spec``  -- static.  Given a bwrap-style argv list (or any
   sequence of mount entries), compute which sensitive paths would be visible.
   Catches the whole-directory state-bind bug class (e.g. ``--ro-bind
   ~/.custodian`` exposing the receipt chain and the receipt HMAC keys).

2. ``scan_live_sandboxes`` -- runtime.  Parse ``/proc/<pid>/mountinfo`` of
   every live bwrap process on this host and flag binds whose source is a
   sensitive path.  This watches what is ACTUALLY mounted right now, even for
   sandboxes built by code this module has never seen.

3. ``probe_containment`` -- empirical.  Plant marker files, run a probe
   command through a real sandbox, and verify the markers are invisible.

Findings are value-free: path + severity + why.  The CLI wrapper
(``scripts/sandbox-audit``) exits non-zero when a critical/high finding is
present so it can be used as a pre-flight gate or a cron watchdog.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

# ---------------------------------------------------------------------------
# Sensitive-path model
# ---------------------------------------------------------------------------
#
# custodian/ must not import paladin/ (architecture boundary), so the deny
# list is defined here, deliberately matching the paladin sandbox's own mask
# list plus the Custodian state-dir contents.

# Default credential / secret homes that must never be visible inside a
# sandbox, even read-only.  Expanded at call time so $HOME moves are honored.
_DEFAULT_DENY_DIRS = (
    ".ssh",
    ".aws",
    ".gnupg",
    ".config/gcloud",
    ".kube",
    ".docker",
    ".paladin",
    ".talaria",
)

# Non-home absolute paths that must never be visible (docker/podman sockets
# would let a sandboxed agent drive the host container runtime).
_DENY_SOCKETS = (
    "/var/run/docker.sock",
    "/run/docker.sock",
    "/run/podman/podman.sock",
)

# Inside the Custodian state dir, only the policy files may be visible (the
# guard reads them to enforce); everything else -- the receipt chain, approval
# store, ledger, tamper evidence, and the *.key HMAC material -- must stay
# invisible.  kill_switch.json is deliberately NOT allowed: a sandboxed agent
# must not learn whether the kill switch is armed.
ALLOWED_STATE_FILES = frozenset({
    "approval-policy.json",
    "control-settings.json",
    "filesystem-policy.json",
    "gate-policy.json",
})


def state_dir() -> Path:
    """The Custodian state dir, honoring the same env vars the guard uses."""
    raw = (os.environ.get("CUSTODIAN_STATE_DIR")
           or os.environ.get("CUSTODIAN_CODEX_GUARD_STATE_DIR")
           or "~/.custodian")
    return Path(raw).expanduser()


def deny_paths() -> list[Path]:
    """Every sensitive path the watchdog must never see inside a sandbox."""
    home = Path.home()
    paths = [home / d for d in _DEFAULT_DENY_DIRS]
    paths += [Path(s) for s in _DENY_SOCKETS]
    # Env-driven secrets (Paladin vault / keyfile) when present.
    for var in ("PALADIN_VAULT_PATH", "PALADIN_KEYFILE"):
        raw = os.environ.get(var)
        if raw:
            paths.append(Path(raw).expanduser())
    return [p for p in paths if p]


def _norm(p: Path) -> str:
    # resolve() (not absolute()) so a symlinked mount source compares as
    # its real target: a source symlink pointing at ~/.ssh must be
    # flagged, not silently audited as the symlink's own path.
    return str(p.expanduser().resolve(strict=False))


def _is_under(path: str, ancestor: str) -> bool:
    """True when ``path`` is ``ancestor`` itself or lives under it.

    Handles the root ancestor specially: every absolute path is under ``/``,
    and naive prefixing would test against ``"//"``.
    """
    if path == ancestor:
        return True
    prefix = ancestor.rstrip(os.sep) + os.sep
    return path.startswith(prefix)


@dataclass(frozen=True)
class Finding:
    """One exposure of a sensitive path by a sandbox mount."""

    severity: str            # "critical" | "high" | "info"
    source: str              # host path that is (or contains) the secret
    exposed: str             # the sensitive path that would be visible
    dest: str                # where it lands inside the sandbox
    writable: bool           # True when bound rw
    why: str = ""

    def __str__(self) -> str:
        return (f"[{self.severity}] {self.source} -> {self.dest} "
                f"({'rw' if self.writable else 'ro'}) exposes {self.exposed}"
                + (f" ({self.why})" if self.why else ""))


_SEVERITY_RANK = {"critical": 3, "high": 2, "info": 1}


def _classify(source: str) -> tuple[str, str]:
    """Return (verdict, exposed_path) for a host source path.

    verdict: "deny" (must never be visible), "allowed" (safe), or
    "ancestor" (a parent of deny paths is bound; masking decides).
    """
    src = _norm(Path(source))
    st = _norm(state_dir())
    # A sensitive path itself, or a file inside one.
    for deny in deny_paths():
        if _is_under(src, _norm(deny)):
            return "deny", src
    # Inside the Custodian state dir: only the named TOP-LEVEL policy files
    # are allowed; a nested file sharing an allowed basename must not be
    # misclassified (e.g. <state>/codex-approvals/approval-policy.json).
    if _is_under(src, st):
        if src == st:
            return "ancestor", src  # whole dir: enumerate its denied children
        if Path(src).parent == Path(st) and Path(src).name in ALLOWED_STATE_FILES:
            return "allowed", ""
        return "deny", src
    # Ancestor of sensitive paths (e.g. binding $HOME or /).
    for deny in deny_paths():
        if _is_under(_norm(deny), src):
            return "ancestor", src
    if _is_under(st, src):
        return "ancestor", src
    return "allowed", ""


def _masked(exposed: str, masks: Sequence[str]) -> bool:
    """True when a mask covers ``exposed`` (mask is an ancestor-or-equal path).

    A mask nested INSIDE the exposed path does not cover it: masking
    ``/home/u/.ssh/nested`` leaves ``/home/u/.ssh/id_rsa`` fully exposed.
    """
    return any(_is_under(exposed, m) for m in masks)


# ---------------------------------------------------------------------------
# 1. Static audit of a mount spec
# ---------------------------------------------------------------------------


@dataclass
class MountEntry:
    """One mount decision in argv order (later entries override earlier)."""

    src: str          # host source path ("" for tmpfs)
    dest: str         # sandbox destination
    rw: bool
    masked: bool = False  # tmpfs: hides whatever was there


# bwrap option arity map: option -> number of value arguments it consumes.
# Everything after the child executable is the child's own argv (inert text as
# far as bwrap is concerned) and MUST NOT be scanned for mount tokens -- a
# trailing "--tmpfs /home/x/.ssh" could otherwise erase a leak finding while
# the real sandbox still exposes the path.  Unknown "--" options are skipped
# without consuming values (conservative).
_BWRAP_OPT_ARITY = {
    "--bind": 2, "--ro-bind": 2, "--bind-try": 2, "--ro-bind-try": 2,
    "--bind-data": 2, "--ro-bind-data": 2, "--setenv": 2, "--symlink": 2,
    "--file": 3, "--lock-file": 1, "--remount-ro": 1,
    "--tmpfs": 1, "--dir": 1, "--dev": 1, "--proc": 1,
    "--uid": 1, "--gid": 1, "--hostname": 1, "--chdir": 1, "--unsetenv": 1,
    "--seccomp": 1, "--size": 1, "--exec-label": 1, "--args": 1,
}


def _bwrap_argv_to_entries(argv: Sequence[str]) -> list[MountEntry]:
    """Convert a bwrap argv list into ordered MountEntry objects.

    Handles ``--bind``, ``--ro-bind``, ``--bind-try``, ``--ro-bind-try``
    (source + dest pairs) and ``--tmpfs`` (mask).  Parsing stops at the
    child-command boundary (the first bare token that is not consumed as an
    option value), matching bwrap's own semantics: everything after the
    executable belongs to the child and must never be interpreted as mounts.
    """
    entries: list[MountEntry] = []
    i = 0
    n = len(argv)
    # argv[0] may be the bwrap program name (a bare token that is neither an
    # option nor the child executable); skip it so parsing starts at the
    # first option.  Callers that pass a pure option list (no program name)
    # are unaffected because their first token starts with "--".
    if i < n and not argv[i].startswith("--"):
        i += 1
    while i < n:
        a = argv[i]
        if a in ("--bind", "--ro-bind", "--bind-try", "--ro-bind-try",
                 "--bind-data", "--ro-bind-data") and i + 2 < n:
            src, dest = argv[i + 1], argv[i + 2]
            entries.append(MountEntry(src=src, dest=dest, rw=not a.startswith("--ro-")))
            i += 3
            continue
        if a == "--tmpfs" and i + 1 < n:
            entries.append(MountEntry(src="", dest=argv[i + 1], rw=True, masked=True))
            i += 2
            continue
        arity = _BWRAP_OPT_ARITY.get(a)
        if arity is not None:
            i += 1 + arity
            continue
        if a.startswith("--"):
            i += 1  # unknown option: skip without consuming values
            continue
        break  # first bare token = child executable: mount parsing ends
    return entries


def analyze_mounts(entries: Sequence[MountEntry]) -> list[Finding]:
    """Reduce an ordered mount list to exposure findings (last-wins)."""
    # Last mount on a destination wins (bwrap semantics).
    final: dict[str, MountEntry] = {}
    for e in entries:
        final[e.dest] = e

    masks = [e.dest for e in final.values() if e.masked]
    # /dev/null binds are recognized null-masks: the destination path is
    # covered (the sandboxed child sees a char device, not the real object).
    masks += [e.dest for e in final.values()
              if not e.masked and e.src == "/dev/null"]
    findings: list[Finding] = []
    for e in final.values():
        if e.masked:
            continue
        verdict, exposed = _classify(e.src)
        if verdict == "allowed":
            continue
        if verdict == "deny":
            findings.append(Finding(
                severity="critical" if e.rw else "high",
                source=e.src, exposed=exposed, dest=e.dest, writable=e.rw,
                why="sensitive path bound into sandbox"))
            continue
        # ancestor: a parent of deny paths is bound; masks decide.
        for deny in deny_paths():
            d = _norm(deny)
            # A path that does not exist on the host cannot be exposed.
            if not os.path.lexists(d):
                continue
            if not _is_under(d, _norm(Path(e.src))):
                continue
            if not _masked(d, masks):
                findings.append(Finding(
                    severity="critical" if e.rw else "high",
                    source=e.src, exposed=d, dest=e.dest, writable=e.rw,
                    why="bound directory contains sensitive path"))
        # The Custodian state dir and its denied children (receipt chain,
        # approval store, ledger, keys, tamper evidence) are exposed when the
        # state dir itself or an ancestor of it is bound without a mask.
        st = _norm(state_dir())
        src = _norm(Path(e.src))
        if _is_under(st, src) or _is_under(src, st):
            if _is_under(st, src) and src != st and not _masked(st, masks):
                findings.append(Finding(
                    severity="critical" if e.rw else "high",
                    source=e.src, exposed=st, dest=e.dest, writable=e.rw,
                    why="Custodian state dir bound into sandbox"))
            if os.path.isdir(st):
                for child in sorted(os.listdir(st)):
                    if child in ALLOWED_STATE_FILES:
                        continue
                    c = os.path.join(st, child)
                    if not _is_under(c, src):
                        continue
                    if _masked(c, masks):
                        continue
                    findings.append(Finding(
                        severity="critical" if e.rw else "high",
                        source=e.src, exposed=c, dest=e.dest, writable=e.rw,
                        why="state-dir content bound into sandbox"))
    return sorted(findings, key=lambda f: -_SEVERITY_RANK[f.severity])


def audit_mount_spec(argv: Sequence[str]) -> list[Finding]:
    """Audit a bwrap-style argv list for sensitive-path exposure."""
    return analyze_mounts(_bwrap_argv_to_entries(argv))


# ---------------------------------------------------------------------------
# 2. Live scan of running sandboxes
# ---------------------------------------------------------------------------

_MOUNTINFO_RE = re.compile(
    r"^\S+ \S+ \S+ \S+ (?P<dest>\S+) \S+(?: \S+)* - (?P<fstype>\S+) (?P<src>\S+)"
)


def _iter_live_bwrap(proc_root: Path = Path("/proc")):
    """Yield (pid, cmdline, [MountEntry]) for every live bwrap process."""
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            if "bwrap" not in cmdline:
                continue
            entries: list[MountEntry] = []
            for line in (proc / "mountinfo").read_text(errors="replace").splitlines():
                m = _MOUNTINFO_RE.match(line)
                if not m:
                    continue
                fstype, src, dest = m.group("fstype"), m.group("src"), m.group("dest")
                if fstype == "tmpfs" or src in ("tmpfs", "proc", "sysfs", "devpts", "mqueue"):
                    if fstype == "tmpfs":
                        entries.append(MountEntry(src="", dest=dest, rw=True, masked=True))
                    continue
                if not src.startswith("/"):
                    continue
                # On btrfs hosts, bind sources show as the DEVICE (e.g.
                # /dev/nvme0n1p8); the real host path is the DESTINATION,
                # because bwrap binds host paths to the same path inside.
                if src.startswith("/dev/"):
                    src = dest
                head = line.split(" - ")[0].split()
                rw = len(head) > 5 and "rw" in head[5].split(",")
                entries.append(MountEntry(src=src, dest=dest, rw=rw))
            yield int(proc.name), cmdline.strip(), entries
        except (OSError, ValueError):
            continue  # pid exited / not readable; skip


def scan_live_sandboxes(proc_root: Path = Path("/proc")) -> dict[int, list[Finding]]:
    """Scan running bwrap processes; return pid -> findings."""
    out: dict[int, list[Finding]] = {}
    for pid, cmdline, entries in _iter_live_bwrap(proc_root):
        findings = analyze_mounts(entries)
        if findings:
            out[pid] = findings
    return out


# ---------------------------------------------------------------------------
# 3. Empirical probe through a real sandbox
# ---------------------------------------------------------------------------


def probe_containment(
    launcher: Sequence[str],
    workspace: Path,
    markers: Optional[dict[str, str]] = None,
    timeout: float = 60.0,
    extra_env: Optional[dict[str, str]] = None,
) -> tuple[int, str]:
    """Run a probe through ``launcher`` and report (exit_code, probe output).

    Plants ``markers`` ({relative path: content}) under a fake HOME inside
    ``workspace``, launches a probe shell that checks each marker is
    invisible, and returns the result.  The probe exits non-zero if any
    marker is visible.  ``extra_env`` is merged into the child environment
    (e.g. HERMES_HOME / CUSTODIAN_STATE_DIR the launcher needs).
    """
    markers = markers or {
        ".ssh/id_rsa": "SECRET-SSH",
        ".paladin/vault.key": "SECRET-VAULT",
        ".custodian/codex-guard-receipts.jsonl": "RECEIPT",
        ".custodian/codex-approval.key": "K" * 32,
    }
    # The fake HOME must live OUTSIDE the workspace: the workspace is the one
    # path the sandbox is allowed to bind read-write, so markers inside it
    # would be visible to a CORRECT sandbox.  A sibling dir stays unmounted.
    home = workspace.parent / ".probe-home"
    for rel in markers:
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(markers[rel])

    checks = []
    for rel in markers:
        checks.append(
            f'test -f "$HOME/{rel}" && echo "LEAK:{rel}" || echo "OK:{rel}"')
    probe = "#!/bin/sh\n" + "\n".join(checks) + '\necho "PROBE_DONE"\n'
    bin_dir = workspace / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    probe_path = bin_dir / "hermes"
    probe_path.write_text(probe)
    probe_path.chmod(0o755)

    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "PATH": f"{bin_dir}:{env.get('PATH', '/usr/bin:/bin')}",
    })
    if extra_env:
        env.update(extra_env)
    r = subprocess.run(
        list(launcher), capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Minimal CLI fallback (the real CLI lives in scripts/sandbox-audit)."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print((__doc__ or "").splitlines()[0])
        return 0
    if args[0] == "live":
        out = scan_live_sandboxes()
        for pid, findings in out.items():
            for f in findings:
                print(f"pid {pid}: {f}")
        return 1 if out else 0
    print("usage: python -m custodian.containment_audit live")
    return 2


if __name__ == "__main__":
    sys.exit(main())
