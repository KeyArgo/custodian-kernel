"""`custodian backup` / `custodian restore` — workspace data safety.

A custodian workspace is plain files: ``policy.yaml`` (the rules) and a
state directory (``custodian.db`` ledger/audit/kill-switch, plus JSON
mirrors). Losing them means losing the audit history and spend state, so
backup is a first-class command, not a "copy some files" footnote.

The backup is one ``.zip``:

* ``policy.yaml`` — as on disk.
* ``state/...`` — every file in the state dir, except that SQLite
  databases are snapshotted through ``sqlite3.Connection.backup()``, the
  engine's own online-backup API. A raw file copy of a database mid-write
  can capture a torn page (silent corruption discovered only on restore
  — the worst possible time); the backup API guarantees a consistent
  snapshot even while the kernel is writing. ``-wal``/``-shm`` sidecars
  are skipped because the snapshot already folds them in.
* ``MANIFEST.json`` — format tag, timestamp, file list.

Restore refuses to overwrite an existing workspace unless ``--force``,
and with ``--force`` it first writes a ``pre-restore-<time>.zip`` of the
current files next to the workspace — a restore can never lose data,
even one pointed at the wrong directory. Archive member paths are
validated against zip-slip before any extraction.

Nothing here is secret material: custodian state contains receipts,
policy, and audit rows, not credentials (those live in the paladin
vault, which has its own ``paladin backup``). The zip is therefore not
encrypted — it is exactly as sensitive as the workspace folder itself.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

MANIFEST_FILENAME = "MANIFEST.json"
BACKUP_FORMAT = "custodian-backup/1"
BACKUP_PREFIX = "custodian-backup-"
DEFAULT_BACKUP_DIR = "~/custodian-backups"


def _snapshot_sqlite(db_path: Path) -> bytes:
    """A consistent point-in-time copy of a SQLite db, safe under writes."""
    fd, tmp_name = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        src = sqlite3.connect(str(db_path))
        try:
            dst = sqlite3.connect(tmp_name)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return Path(tmp_name).read_bytes()
    finally:
        os.unlink(tmp_name)


def _workspace_files(policy: Path, state_dir: Path) -> list[tuple[str, Path]]:
    """(archive_name, disk_path) pairs for everything worth backing up."""
    files: list[tuple[str, Path]] = []
    if policy.exists():
        files.append(("policy.yaml", policy))
    if state_dir.is_dir():
        for p in sorted(state_dir.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix in (".db-wal", ".db-shm") or p.name.endswith(("-wal", "-shm")):
                continue  # folded into the sqlite snapshot
            files.append((f"state/{p.relative_to(state_dir).as_posix()}", p))
    return files


def _resolve_dest(dest: str | None) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    name = f"{BACKUP_PREFIX}{stamp}.zip"
    if dest is None:
        return Path(DEFAULT_BACKUP_DIR).expanduser() / name
    p = Path(dest).expanduser()
    if p.is_dir():
        return p / name
    return p


def run_backup(args) -> int:
    policy = Path(getattr(args, "policy", None) or "policy.yaml")
    state_dir = Path(args.state_dir)

    files = _workspace_files(policy, state_dir)
    if not files:
        print(f"Nothing to back up: no {policy} and no state in {state_dir}/.")
        print("If your workspace lives elsewhere, run this from that directory")
        print("(or pass --state-dir). To create a workspace: custodian init")
        return 1

    dest = _resolve_dest(getattr(args, "dest", None))
    if dest.exists():
        if not getattr(args, "force", False):
            print(f"error: {dest} already exists — choose another path or pass --force")
            return 1
        dest.unlink()

    manifest = {
        "format": BACKUP_FORMAT,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "files": [name for name, _ in files],
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_FILENAME, json.dumps(manifest, indent=2))
            for name, path in files:
                if path.suffix == ".db":
                    zf.writestr(name, _snapshot_sqlite(path))
                else:
                    zf.write(path, name)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)

    print(f"Backed up {len(files)} file(s) → {dest}")
    for name, _ in files:
        print(f"  {name}")
    if getattr(args, "dest", None) is None:
        print()
        print("NOTE: this backup lives on the SAME computer as the workspace.")
        print("Copy it to a USB drive, another machine, or cloud storage for")
        print("real protection.")
    print()
    print("To restore (here or on another machine):")
    print(f"  custodian restore \"{dest}\"")
    return 0


def run_restore(args) -> int:
    src = Path(args.source).expanduser()
    if not src.exists():
        print(f"error: no backup file at {src}")
        return 1
    if not zipfile.is_zipfile(src):
        print(f"error: {src} is not a backup archive (expected a .zip from "
              f"`custodian backup`)")
        return 1

    policy = Path(getattr(args, "policy", None) or "policy.yaml")
    state_dir = Path(args.state_dir)

    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        if MANIFEST_FILENAME not in names:
            print(f"error: {src} is a zip but not a custodian backup "
                  f"(no {MANIFEST_FILENAME} inside)")
            return 1
        manifest = json.loads(zf.read(MANIFEST_FILENAME))
        if manifest.get("format") != BACKUP_FORMAT:
            print(f"error: unrecognized backup format "
                  f"{manifest.get('format')!r} (this custodian understands "
                  f"{BACKUP_FORMAT})")
            return 1
        members = [n for n in names if n != MANIFEST_FILENAME]
        # zip-slip guard: every member must be a plain relative path that
        # stays inside the workspace once mapped.
        for n in members:
            norm = Path(n)
            if norm.is_absolute() or ".." in norm.parts:
                print(f"error: refusing to restore — unsafe path in archive: {n!r}")
                return 1
            if not (n == "policy.yaml" or n.startswith("state/")):
                print(f"error: refusing to restore — unexpected member: {n!r}")
                return 1

        existing = _workspace_files(policy, state_dir)
        if existing and not getattr(args, "force", False):
            print(f"error: this directory already has a workspace "
                  f"({len(existing)} file(s): {policy}, {state_dir}/...).")
            print("Pass --force to replace it — the current files are first")
            print("saved to a pre-restore-<time>.zip right here, so nothing is lost.")
            return 1

        if existing:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
            safety = Path(f"pre-restore-{stamp}.zip")
            with zipfile.ZipFile(safety, "w", compression=zipfile.ZIP_DEFLATED) as sz:
                sz.writestr(MANIFEST_FILENAME, json.dumps(
                    {"format": BACKUP_FORMAT,
                     "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
                     "files": [n for n, _ in existing],
                     "note": "automatic safety copy made by `custodian restore --force`"},
                    indent=2))
                for name, path in existing:
                    if path.suffix == ".db":
                        sz.writestr(name, _snapshot_sqlite(path))
                    else:
                        sz.write(path, name)
            print(f"saved the current workspace to {safety} before restoring")

        restored = []
        for n in members:
            if n == "policy.yaml":
                target = policy
            else:  # state/...
                target = state_dir / Path(n).relative_to("state")
            target.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(n)
            tmp = target.with_suffix(target.suffix + ".tmp")
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
            # A restored db supersedes any journal left by the previous db.
            if target.suffix == ".db":
                for sidecar in (Path(str(target) + "-wal"), Path(str(target) + "-shm")):
                    sidecar.unlink(missing_ok=True)
            restored.append(n)

    print(f"Restored {len(restored)} file(s):")
    for n in restored:
        print(f"  {n}")
    print()
    print("Check it: custodian status")
    return 0
