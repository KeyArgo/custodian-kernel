"""Bulk credential import: .env files, Bitwarden, 1Password, discovery.

The pipeline is: a *source* yields :class:`Candidate` objects (name, value,
kind, provenance), and :func:`import_candidates` feeds them into the vault
with deduplication. Every function that returns anything designed to be
shown — reports, discovery results, dry-runs — carries **names and metadata
only, never values**. That is the paladin contract (the agent never sees
the value), and it holds even though this module is what agents call to do
imports: the value goes subprocess-JSON → this process → AES-256-GCM vault,
and dies with the process.

Kind inference: well-known credential prefixes identify what a value is
(``ghp_`` is a GitHub token no matter what the entry is called), falling
back to name hints, then ``password``.

Discovery (:func:`discover`) is deliberately report-only. It says *where*
credentials probably live (.env files, shell-rc exports by NAME, whether
``bw``/``op`` are installed and unlocked) and what to run next; importing
requires an explicit source command. A tool that silently harvested
everything it could find would be indistinguishable from malware — the
human stays in the loop at exactly this line.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from paladin.errors import PaladinError
from paladin.refs import valid_name
from paladin.vault import Vault

# -- kind inference -----------------------------------------------------------

# Value-prefix → kind. Checked first: the value's own shape is the most
# reliable signal (a GitHub PAT is a token even if the entry is called
# "my-password"). Order matters only where prefixes overlap; keep the more
# specific first.
VALUE_KIND_PATTERNS: list[tuple[str, str]] = [
    ("github_pat_", "token"),   # GitHub fine-grained PAT
    ("ghp_", "token"),          # GitHub classic PAT
    ("gho_", "token"),          # GitHub OAuth
    ("ghs_", "token"),          # GitHub server-to-server
    ("tskey-", "token"),        # Tailscale
    ("xoxb-", "token"),         # Slack bot
    ("xoxp-", "token"),         # Slack user
    ("re_", "token"),           # Resend
    ("sk-or-v1-", "secret"),    # OpenRouter
    ("sk-ant-", "secret"),      # Anthropic
    ("sk-", "secret"),          # OpenAI-style
    ("sk_live_", "secret"),     # Stripe live
    ("sk_test_", "secret"),     # Stripe test
    ("rk_live_", "secret"),     # Stripe restricted
    ("pk_live_", "secret"),
    ("pk_test_", "secret"),
    ("pplx-", "secret"),        # Perplexity
    ("nvapi-", "secret"),       # NVIDIA NIM
    ("AKIA", "secret"),         # AWS access key id
    ("AIza", "secret"),         # Google API
    ("hf_", "token"),           # HuggingFace
    ("glpat-", "token"),        # GitLab
    ("dop_v1_", "token"),       # DigitalOcean
    ("eyJ", "token"),           # JWT-shaped
]

# Name-substring → kind, when the value has no telltale prefix.
NAME_KIND_HINTS: list[tuple[str, str]] = [
    ("password", "password"),
    ("passwd", "password"),
    ("token", "token"),
    ("api_key", "secret"),
    ("apikey", "secret"),
    ("secret", "secret"),
    ("key", "secret"),
]


def infer_kind(name: str, value: str) -> str:
    for prefix, kind in VALUE_KIND_PATTERNS:
        if value.startswith(prefix):
            return kind
    lowered = name.lower()
    for hint, kind in NAME_KIND_HINTS:
        if hint in lowered:
            return kind
    return "password"


# -- candidates & report ------------------------------------------------------

@dataclass
class Candidate:
    """One credential on its way into the vault."""

    name: str
    value: str
    env_var: Optional[str] = None
    kind: Optional[str] = None          # None → infer at import time
    note: str = ""
    source: str = ""                    # "env:.../.env", "bitwarden:item-name", ...
    flags: list[str] = field(default_factory=list)  # e.g. ["git-tracked"]

    def resolved_kind(self) -> str:
        return self.kind or infer_kind(self.name, self.value)


@dataclass
class ImportReport:
    """Everything about an import EXCEPT the values — safe to show/return."""

    imported: list[dict] = field(default_factory=list)   # {name, kind, source, flags}
    skipped_existing: list[str] = field(default_factory=list)
    skipped_invalid: list[str] = field(default_factory=list)
    flagged: list[dict] = field(default_factory=list)    # {name, source, flags}
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "dry_run": self.dry_run,
            "imported": self.imported,
            "imported_count": len(self.imported),
            "skipped_existing": self.skipped_existing,
            "skipped_invalid": self.skipped_invalid,
            "flagged": self.flagged,
        }


def _safe_name(raw: str) -> Optional[str]:
    """Normalize an arbitrary entry title into a valid vault name."""
    name = raw.strip().lower()
    name = re.sub(r"[^a-z0-9/_.-]+", "_", name).strip("_")
    name = re.sub(r"_{2,}", "_", name)
    if name and valid_name(name):
        return name
    return None


# -- source: .env files -------------------------------------------------------

# Directories that are never a sensible place to look for the user's own
# .env files, and are huge.
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__",
              ".tox", ".mypy_cache", "site-packages", ".cache"}

_EXPORT_RE = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def parse_env_text(text: str, source: str) -> list[Candidate]:
    """KEY=value lines (with optional ``export``) → candidates."""
    out: list[Candidate] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _EXPORT_RE.match(stripped)
        if not m:
            continue
        key, value = m.group(1), m.group(2)
        value = value.split(" #")[0].strip().strip("'\"")
        if not key or not value:
            continue
        # $VAR / $(cmd) / `cmd` values are references, not credentials.
        if value.startswith(("$", "`")):
            continue
        out.append(Candidate(name=key.lower(), value=value, env_var=key,
                             source=source))
    return out


def collect_env_files(root: Path, pattern: str = ".env*",
                      recursive: bool = False, max_files: int = 200) -> list[Path]:
    root = Path(root)
    if root.is_file():
        return [root]
    found: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                if fnmatch.fnmatch(fn, pattern):
                    found.append(Path(dirpath) / fn)
                    if len(found) >= max_files:
                        return found
    else:
        found = [p for p in sorted(root.glob(pattern)) if p.is_file()]
    return found


def git_exposure_flags(path: Path) -> list[str]:
    """Is this credentials file exposed through git?

    ``git-tracked`` — the file is committed history waiting to happen (or
    already is); ``git-unignored`` — untracked but nothing stops a
    ``git add .`` from sweeping it in. Both mean: rotate/clean up after
    vaulting. Returns [] when git is absent or the file isn't in a repo.
    """
    git = shutil.which("git")
    if git is None:
        return []
    path = Path(path).resolve()
    try:
        inside = subprocess.run(
            [git, "-C", str(path.parent), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, encoding="utf-8", timeout=10)
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return []
        tracked = subprocess.run(
            [git, "-C", str(path.parent), "ls-files", "--error-unmatch", path.name],
            capture_output=True, text=True, encoding="utf-8", timeout=10)
        if tracked.returncode == 0:
            return ["git-tracked"]
        ignored = subprocess.run(
            [git, "-C", str(path.parent), "check-ignore", "-q", path.name],
            capture_output=True, text=True, encoding="utf-8", timeout=10)
        if ignored.returncode != 0:
            return ["git-unignored"]
    except (subprocess.TimeoutExpired, OSError):
        return []
    return []


def candidates_from_env(path: Path) -> list[Candidate]:
    path = Path(path)
    flags = git_exposure_flags(path)
    cands = parse_env_text(path.read_text(encoding="utf-8", errors="replace"),
                           source=f"env:{path}")
    for c in cands:
        c.flags = list(flags)
    return cands


# -- source: Bitwarden (bw CLI) ------------------------------------------------

def _run_json(cmd: list[str], timeout: float = 30) -> object:
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip()[-300:]
        raise PaladinError(f"`{cmd[0]}` failed: {tail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise PaladinError(f"`{cmd[0]}` returned non-JSON output") from e


def bitwarden_status() -> dict:
    """{"installed": bool, "unlocked": bool, "hint": str}."""
    bw = shutil.which("bw")
    if bw is None:
        return {"installed": False, "unlocked": False,
                "hint": "install the Bitwarden CLI: https://bitwarden.com/help/cli/"}
    try:
        status = _run_json([bw, "status"])
    except PaladinError:
        return {"installed": True, "unlocked": False,
                "hint": "run: bw login && export BW_SESSION=$(bw unlock --raw)"}
    unlocked = isinstance(status, dict) and status.get("status") == "unlocked"
    return {"installed": True, "unlocked": unlocked,
            "hint": "" if unlocked else
            "run: export BW_SESSION=$(bw unlock --raw)"}


def bitwarden_candidates(search: Optional[str] = None,
                         folder: Optional[str] = None) -> list[Candidate]:
    bw = shutil.which("bw")
    if bw is None:
        raise PaladinError("Bitwarden CLI (`bw`) is not installed")
    st = bitwarden_status()
    if not st["unlocked"]:
        raise PaladinError(f"Bitwarden vault is locked — {st['hint']}")

    cmd = [bw, "list", "items"]
    if search:
        cmd += ["--search", search]
    if folder:
        folders = _run_json([bw, "list", "folders"])
        match = [f for f in folders
                 if f.get("name", "").lower() == folder.lower()]
        if not match:
            raise PaladinError(f"no Bitwarden folder named {folder!r}")
        cmd += ["--folderid", match[0]["id"]]
    items = _run_json(cmd)

    out: list[Candidate] = []
    for item in items:
        title = item.get("name") or "unnamed"
        base = _safe_name(title)
        if base is None:
            continue
        note = f"imported from Bitwarden item '{title}'"
        login = item.get("login") or {}
        if login.get("password"):
            out.append(Candidate(name=base, value=login["password"],
                                 note=note, source=f"bitwarden:{title}"))
        for f in item.get("fields") or []:
            fname, fval = f.get("name"), f.get("value")
            if not fname or not fval:
                continue
            sub = _safe_name(f"{base}/{fname}")
            if sub is None:
                continue
            out.append(Candidate(name=sub, value=fval, note=note,
                                 source=f"bitwarden:{title}"))
    return out


# -- source: 1Password (op CLI) --------------------------------------------------

# Field labels that are metadata, not credentials.
_OP_SKIP_LABELS = {"username", "url", "website", "notes", "notesplain"}


def onepassword_status() -> dict:
    op = shutil.which("op")
    if op is None:
        return {"installed": False, "signed_in": False,
                "hint": "install the 1Password CLI: https://developer.1password.com/docs/cli/"}
    try:
        result = subprocess.run([op, "whoami"], capture_output=True, text=True,
                                encoding="utf-8", timeout=15)
        signed_in = result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        signed_in = False
    return {"installed": True, "signed_in": signed_in,
            "hint": "" if signed_in else "run: op signin"}


def onepassword_candidates(vault: Optional[str] = None,
                           search: Optional[str] = None) -> list[Candidate]:
    op = shutil.which("op")
    if op is None:
        raise PaladinError("1Password CLI (`op`) is not installed")
    st = onepassword_status()
    if not st["signed_in"]:
        raise PaladinError(f"1Password CLI is not signed in — {st['hint']}")

    cmd = [op, "item", "list", "--format", "json"]
    if vault:
        cmd += ["--vault", vault]
    listing = _run_json(cmd)
    if search:
        needle = search.lower()
        listing = [i for i in listing if needle in (i.get("title") or "").lower()]

    out: list[Candidate] = []
    for stub in listing:
        item_id = stub.get("id")
        title = stub.get("title") or "unnamed"
        if not item_id:
            continue
        get_cmd = [op, "item", "get", item_id, "--format", "json"]
        if vault:
            get_cmd += ["--vault", vault]
        item = _run_json(get_cmd)
        base = _safe_name(title)
        if base is None:
            continue
        note = f"imported from 1Password item '{title}'"
        for f in item.get("fields") or []:
            label = (f.get("label") or f.get("id") or "").strip()
            value = f.get("value")
            ftype = (f.get("type") or "").upper()
            purpose = (f.get("purpose") or "").upper()
            if not value or label.lower() in _OP_SKIP_LABELS:
                continue
            if purpose == "PASSWORD" or ftype == "CONCEALED":
                sub = base if purpose == "PASSWORD" else _safe_name(f"{base}/{label}")
                if sub is None:
                    continue
                kind = "password" if purpose == "PASSWORD" else None
                out.append(Candidate(name=sub, value=value, kind=kind,
                                     note=note, source=f"1password:{title}"))
    return out


# -- discovery (report-only) ---------------------------------------------------

_SHELL_RC_FILES = [".bashrc", ".zshrc", ".profile", ".bash_profile", ".zprofile"]

# Only exports whose NAME looks credential-ish are worth reporting; TERM,
# PATH and friends are noise. Never report the value.
_CREDENTIAL_NAME_RE = re.compile(
    r"(?i)(key|token|secret|passw|credential|auth)")


def discover(home: Optional[Path] = None, cwd: Optional[Path] = None) -> dict:
    """Where do credentials live on this machine? Names and places only.

    Report-only by design (see module docstring): the output tells a human
    — or an agent relaying to a human — what exists and the exact command
    to import each source. Nothing is read into the vault here.
    """
    home = Path(home) if home else Path.home()
    cwd = Path(cwd) if cwd else Path.cwd()

    env_files: list[dict] = []
    seen: set = set()
    for base in (cwd, home):
        for p in collect_env_files(base, pattern=".env*", recursive=False):
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            try:
                count = len(parse_env_text(
                    p.read_text(encoding="utf-8", errors="replace"), ""))
            except OSError:
                continue
            if count:
                env_files.append({"path": str(p), "entries": count,
                                  "flags": git_exposure_flags(p),
                                  "import_with": f"paladin import env \"{p}\""})

    rc_exports: list[dict] = []
    for rc in _SHELL_RC_FILES:
        p = home / rc
        if not p.exists():
            continue
        names = []
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if not s.startswith("export "):
                    continue
                m = _EXPORT_RE.match(s)
                if m and m.group(2) and not m.group(2).startswith(("$", "`")) \
                        and _CREDENTIAL_NAME_RE.search(m.group(1)):
                    names.append(m.group(1))
        except OSError:
            continue
        if names:
            rc_exports.append({"path": str(p), "names": names,
                               "import_with": f"paladin import env \"{p}\""})

    bw = bitwarden_status()
    op = onepassword_status()
    return {
        "ok": True,
        "env_files": env_files,
        "shell_rc_exports": rc_exports,
        "bitwarden": {**bw, "import_with":
                      "paladin import bitwarden [--search TERM] [--folder NAME]"},
        "onepassword": {**op, "import_with":
                        "paladin import 1password [--vault NAME] [--search TERM]"},
    }


# -- the sink: import into the vault --------------------------------------------

def import_candidates(vault: Vault, candidates: Iterable[Candidate],
                      profile: str = "default", dry_run: bool = False,
                      skip_existing: bool = True) -> ImportReport:
    """Feed candidates into the vault. The returned report never holds values.

    ``skip_existing=True`` (the default) makes re-runs idempotent: what is
    already vaulted is left untouched, so an import can be re-pointed at the
    same source safely. ``skip_existing=False`` overwrites (a rotation)."""
    report = ImportReport(dry_run=dry_run)
    existing = set(vault.names())
    seen_this_run: set = set()
    for cand in candidates:
        name = cand.name if valid_name(cand.name) else _safe_name(cand.name)
        if name is None or not cand.value:
            report.skipped_invalid.append(cand.name)
            continue
        if name in seen_this_run or (skip_existing and name in existing):
            report.skipped_existing.append(name)
            continue
        seen_this_run.add(name)
        kind = cand.resolved_kind()
        entry = {"name": name, "kind": kind, "source": cand.source,
                 "flags": cand.flags}
        if cand.flags:
            report.flagged.append({"name": name, "source": cand.source,
                                   "flags": cand.flags})
        if not dry_run:
            vault.add(name, cand.value, kind=kind, profile=profile,
                      env_var=cand.env_var, note=cand.note,
                      overwrite=not skip_existing)
        report.imported.append(entry)
    return report
