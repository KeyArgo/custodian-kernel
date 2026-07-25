"""The guarantee the operator asked for, enforced mechanically: no credential
ever reaches the repo. This fails the build if a vault, keyfile, backup, .env,
or a live-key-shaped value is ever committed — so "your secrets stay on device"
is a test, not a promise.

Vaults live in ~/.paladin (outside the checkout) and backups default to
~/paladin-backups, so in normal use nothing here is even at risk; this catches
the accident (a vault created inside the repo, a real key pasted into a file).
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=str(REPO),
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return [f for f in out.stdout.splitlines() if f.strip()]


# Filenames that are credential material and must never be tracked.
# Real vault files are vault.paladin / vault.warden, caught by the .paladin /
# .warden extension rules -- NOT paladin/vault.py, the source module.
_FORBIDDEN_NAME = re.compile(
    r"(\.paladin$|\.warden$|\.pem$|\.key$|\.keyfile$|"
    r"(^|/)id_rsa$|(^|/)id_ed25519$|paladin-backup-.*\.zip$|\.pre-restore$)",
    re.IGNORECASE,
)

# A real .env (not an example/template) is credential material.
_ENV_FILE = re.compile(r"(^|/)\.env(\.|$)", re.IGNORECASE)
_ENV_OK = re.compile(r"\.(example|template|sample)$", re.IGNORECASE)


def test_no_credential_files_are_tracked():
    bad = []
    for f in _tracked_files():
        if _FORBIDDEN_NAME.search(f):
            bad.append(f)
        elif _ENV_FILE.search(f) and not _ENV_OK.search(f):
            bad.append(f)
    assert not bad, (
        "credential-material files are tracked in git — remove them and add to "
        ".gitignore:\n  " + "\n  ".join(bad)
    )


# Live-credential prefixes. Test/demo files legitimately use fakes, so the
# value scan excludes tests/, docs, and *.example — a REAL key in shipping
# source or config is what this catches.
_LIVE_KEY = re.compile(
    r"(sk_live_[A-Za-z0-9]{20,}|rk_live_[A-Za-z0-9]{20,}|"
    r"ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}|"
    r"AKIA[A-Z0-9]{16}|xoxb-[0-9]{10,}|sk-ant-[A-Za-z0-9-]{40,})"
)


def _is_scannable(f: str) -> bool:
    if f.startswith("tests/") or "/tests/" in f:
        return False
    if f.endswith((".md", ".example", ".template", ".sample", ".lock")):
        return False
    # Adversarial-input generators legitimately embed fake, credential-shaped
    # strings on purpose (they test that the guard's own SecretLeakGuard
    # denies exactly this shape) -- same rationale as the tests/ exclusion
    # above, just for a script that isn't itself under tests/.
    if f == "scripts/harden_guard.py":
        return False
    return f.endswith((".py", ".toml", ".yaml", ".yml", ".json", ".env",
                       ".sh", ".txt", ".cfg", ".ini", ".html", ".js"))


def test_no_live_key_values_in_shipping_source():
    hits = []
    for f in _tracked_files():
        if not _is_scannable(f):
            continue
        p = REPO / f
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if _LIVE_KEY.search(text):
            hits.append(f)
    assert not hits, (
        "a live-credential-shaped value appears in tracked source/config:\n  "
        + "\n  ".join(hits) + "\nRotate it immediately and remove it from the file."
    )
