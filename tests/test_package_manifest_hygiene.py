"""Wheel manifest hygiene guard.

Incident this exists to prevent: custodian-kernel shipped
custodian/custodian/policy/enforcer.py -- a self-nested duplicate
directory, accidentally created during a manual sync into the mirror
repo (never present in this source tree) -- in every published wheel
from v0.3.0 through v0.4.0. It was dead weight (nothing imports the
custodian.custodian.* path), but it was a stale, misleading copy of
enforcer.py shipped to every installer for three releases, and 2300+
passing tests never caught it because none of them asked "what files
are actually in the built wheel" -- they test behavior, not package
manifest hygiene. `packages.find`'s broad `include = ["custodian*",
"paladin*", "caduceus*"]` pattern (pyproject.toml) sweeps up any
directory matching those globs at any depth, so a self-nested duplicate
is silently included rather than rejected.

Two layers, cheapest-first: a fast structural check on the source tree
(catches the mistake immediately, before anyone even builds a wheel),
and a slower check on the actual built wheel's real file manifest (so a
bug in the structural check, or a new packaging mechanism added later,
can't silently let the same bug class back in).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAMES = ["custodian", "paladin", "caduceus"]


def _self_nested_duplicate_dirs(root: Path, package_names: list[str]) -> list[Path]:
    hits = []
    for name in package_names:
        pkg_root = root / name
        if not pkg_root.is_dir():
            continue
        for path in pkg_root.rglob(name):
            if path.is_dir():
                hits.append(path)
    return hits


def test_no_self_nested_duplicate_package_directories():
    hits = _self_nested_duplicate_dirs(REPO_ROOT, PACKAGE_NAMES)
    assert not hits, (
        f"self-nested duplicate package directories found: {hits} -- these "
        "get swept into the wheel by packages.find's broad include pattern "
        "and ship as dead cruft (or worse, stale/misleading code, as "
        "happened in custodian-kernel 0.3.0-0.4.0). Delete them; if this is "
        "a genuine intentional nested package, rename it to something that "
        "doesn't collide with an ancestor package's own name."
    )


def test_built_wheel_has_no_self_nested_duplicate_paths():
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", tmp, str(REPO_ROOT)],
            check=True, capture_output=True, text=True,
        )
        wheel = next(Path(tmp).glob("*.whl"))
        with zipfile.ZipFile(wheel) as zf:
            names = zf.namelist()

    bad = [n for n in names for pkg in PACKAGE_NAMES if f"{pkg}/{pkg}/" in n]
    assert not bad, f"self-nested duplicate paths shipped in the built wheel: {bad}"
