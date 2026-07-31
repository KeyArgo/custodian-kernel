#!/usr/bin/env python3
"""PEP-668-safe Custodian application installer.

Creates a private managed runtime and exposes simple commands. Users never
activate or manage the virtual environment, and package operations never touch
Custodian, Paladin, or Talaria data directories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

DEFAULT_PACKAGES = ("custodian-kernel", "custodian-codex-guard")
COMMANDS = (
    "custodian",
    "custodian-verify",
    "paladin",
    "paladin-import",
    "custodian-codex",
    "custodian-codex-guard-mcp",
    "custodian-codex-guard-hook",
)


def default_runtime_root() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Custodian"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "custodian"


def default_bin_dir() -> Path:
    if os.name == "nt":
        return default_runtime_root() / "bin"
    return Path.home() / ".local/bin"


def _runtime_python(runtime: Path) -> Path:
    return runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _runtime_command(runtime: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    folder = "Scripts" if os.name == "nt" else "bin"
    return runtime / folder / f"{name}{suffix}"


def _validate_managed_paths(runtime_root: Path, bin_dir: Path) -> tuple[Path, Path]:
    """Reject broad or aliased paths before any recursive operation."""
    if runtime_root.expanduser().is_symlink():
        raise ValueError("managed runtime root must not be a symbolic link")
    runtime_root = runtime_root.expanduser().resolve()
    bin_dir = bin_dir.expanduser().resolve()
    home = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
    if (runtime_root == runtime_root.parent or bin_dir == bin_dir.parent
            or os.path.normcase(str(runtime_root)) == home
            or os.path.normcase(str(bin_dir)) == home):
        raise ValueError("runtime and command directories must not be / or the home directory")
    if runtime_root == bin_dir or runtime_root in bin_dir.parents:
        raise ValueError("command directory must not be inside the managed runtime")
    return runtime_root, bin_dir


def _expose(
    command: str, target: Path, bin_dir: Path, runtime_root: Path | None = None
) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    destination = bin_dir / (f"{command}.cmd" if os.name == "nt" else command)
    if destination.exists() or destination.is_symlink():
        owned = False
        if runtime_root is not None:
            if destination.is_symlink():
                owned = destination.resolve(strict=False).is_relative_to(runtime_root)
            elif os.name == "nt":
                try:
                    owned = str(runtime_root) in destination.read_text(encoding="utf-8")
                except OSError:
                    owned = False
        if owned:
            destination.unlink()
        else:
            backup = destination.with_name(destination.name + ".previous")
            backup.unlink(missing_ok=True)
            destination.replace(backup)
    if os.name == "nt":
        destination.write_text(f'@echo off\r\n"{target}" %*\r\n', encoding="utf-8")
    else:
        destination.symlink_to(target)


def install(spec: str | list[str] | tuple[str, ...], runtime_root: Path, bin_dir: Path) -> Path:
    runtime_root, bin_dir = _validate_managed_paths(runtime_root, bin_dir)
    runtime_root.mkdir(parents=True, exist_ok=True)
    active_file = runtime_root / "active-slot"
    active_name = ""
    if active_file.is_file():
        active_name = active_file.read_text(encoding="utf-8").strip()
    slot_name = "runtime-b" if active_name == "runtime-a" else "runtime-a"
    candidate = runtime_root / slot_name
    if candidate.exists():
        shutil.rmtree(candidate)
    # A venv's generated scripts contain absolute interpreter paths. Build in
    # the final slot and never rename it; renaming a staged venv makes every
    # installed command fail with "bad interpreter".
    venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt").create(candidate)
    specs = [spec] if isinstance(spec, str) else list(spec)
    if not specs:
        raise ValueError("at least one package is required")
    subprocess.run(
        [str(_runtime_python(candidate)), "-m", "pip", "install", "--upgrade", *specs],
        check=True,
    )
    subprocess.run(
        [str(_runtime_python(candidate)), "-m", "custodian.cli.main", "doctor"],
        check=True,
    )
    for command in COMMANDS:
        target = _runtime_command(candidate, command)
        if not target.is_file():
            continue
        _expose(
            command, target, bin_dir,
            runtime_root=runtime_root,
        )
    marker = runtime_root / "active-slot.installing"
    marker.write_text(slot_name + "\n", encoding="utf-8")
    marker.replace(active_file)

    # Store provenance plus a digest of pip's installed RECORD. The original
    # wheel is not retained inside a venv, so claiming to re-hash it later
    # would be false verification.
    if len(specs) == 1 and specs[0].endswith(".whl"):
        wheel_path = Path(specs[0])
        if wheel_path.is_file():
            whl_hash = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
            site_roots = (
                list((candidate / "Lib/site-packages").glob("custodian_kernel-*.dist-info/RECORD"))
                if os.name == "nt"
                else list(candidate.glob("lib/python*/site-packages/custodian_kernel-*.dist-info/RECORD"))
            )
            if len(site_roots) != 1:
                raise RuntimeError(
                    f"expected one installed custodian-kernel RECORD, found {site_roots}"
                )
            record = site_roots[0]
            proof = {
                "schema": 1,
                "artifact_sha256": whl_hash,
                "record_sha256": hashlib.sha256(record.read_bytes()).hexdigest(),
                "record_relative": str(record.relative_to(candidate)),
            }
            for hdir in (candidate, runtime_root):
                (hdir / "release-artifact.sha256").write_text(whl_hash + "\n", encoding="utf-8")
                (hdir / "installation-proof.json").write_text(
                    json.dumps(proof, sort_keys=True) + "\n", encoding="utf-8"
                )

    return candidate


def uninstall(runtime_root: Path, bin_dir: Path) -> None:
    """Remove only this managed installation, preserving all user data."""
    runtime_root, bin_dir = _validate_managed_paths(runtime_root, bin_dir)
    for command in COMMANDS:
        destination = bin_dir / (f"{command}.cmd" if os.name == "nt" else command)
        if not (destination.exists() or destination.is_symlink()):
            continue
        owned = False
        if destination.is_symlink():
            try:
                owned = destination.resolve(strict=False).is_relative_to(runtime_root)
            except OSError:
                owned = False
        elif os.name == "nt":
            try:
                owned = str(runtime_root) in destination.read_text(encoding="utf-8")
            except OSError:
                owned = False
        if owned:
            destination.unlink()
            backup = destination.with_name(destination.name + ".previous")
            if backup.exists() or backup.is_symlink():
                backup.replace(destination)
    if runtime_root.exists():
        removed = runtime_root.with_name(runtime_root.name + ".removed")
        if removed.exists():
            shutil.rmtree(removed)
        runtime_root.replace(removed)
    print("Managed Custodian runtime removed.")
    print("User data was preserved.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install or uninstall Custodian's managed runtime"
    )
    parser.add_argument(
        "--package", action="append",
        help=(
            "Package name, version, URL, or local wheel; repeat for multiple "
            "packages (default: custodian-kernel plus custodian-codex-guard)"
        ),
    )
    parser.add_argument("--runtime-root", type=Path, default=default_runtime_root())
    parser.add_argument("--bin-dir", type=Path, default=default_bin_dir())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Remove the managed runtime and its launchers; preserve all user data",
    )
    args = parser.parse_args()
    if args.dry_run:
        print(f"managed runtime: {args.runtime_root}")
        print(f"commands: {args.bin_dir}")
        packages = args.package or list(DEFAULT_PACKAGES)
        print("action: uninstall" if args.uninstall else f"packages: {', '.join(packages)}")
        print("user data: preserved")
        return 0
    if args.uninstall:
        uninstall(args.runtime_root, args.bin_dir)
        return 0
    runtime = install(args.package or DEFAULT_PACKAGES, args.runtime_root, args.bin_dir)
    print(f"Custodian installed: {runtime}")
    print(f"Commands available in: {args.bin_dir}")
    print("User data was preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
