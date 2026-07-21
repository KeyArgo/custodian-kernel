#!/usr/bin/env python3
"""Developer install/update script for Custodian Kernel.

Modes
-----
editable   pip install -e ".[dev]"  (default - live-reload source changes)
fresh      Create a new venv, then editable-install into it
upgrade    pip install --upgrade ".[dev]"
repair     pip install --force-reinstall --no-cache-dir -e ".[dev]"

Usage
-----
    python scripts/dev-install.py                 # editable (default)
    python scripts/dev-install.py --mode fresh
    python scripts/dev-install.py --mode upgrade
    python scripts/dev-install.py --mode repair
    python scripts/dev-install.py --print-pip-cmd  # show the pip command
    python scripts/dev-install.py --dry-run        # show what would be done
    python scripts/dev-install.py --verbose        # detailed output

Each mode is idempotent: running it twice is safe.
No secrets, credentials, shell, git, or network tools are used.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODES = ("editable", "fresh", "upgrade", "repair")


def _pip_install_args(mode: str, dry_run: bool) -> list[str]:
    spec = f"{PROJECT_ROOT}[dev]"
    base = [sys.executable, "-m", "pip", "install"]
    if dry_run:
        base.append("--dry-run")

    if mode == "editable":
        return [*base, "-e", spec]
    if mode == "fresh":
        return [*base, "--ignore-installed", "-e", spec]
    if mode == "upgrade":
        return [*base, "--upgrade", "-e", spec]
    if mode == "repair":
        return [*base, "--force-reinstall", "--no-cache-dir", "-e", spec]
    msg = f"Unknown mode: {mode}"
    raise ValueError(msg)


def _check_installed() -> bool:
    try:
        import custodian  # noqa: F401
        return True
    except ImportError:
        return False


def _pip_cmd(mode: str) -> str:
    return subprocess.list2cmdline(_pip_install_args(mode, dry_run=False))


def _run_pip(mode: str, verbose: bool, dry_run: bool) -> int:
    if dry_run:
        print(f"[dry-run] Would run: {_pip_cmd(mode)}")
        return 0

    args = _pip_install_args(mode, dry_run=False)
    if verbose:
        print(f"Running: {subprocess.list2cmdline(args)}")

    result = subprocess.run(
        args,
        capture_output=not verbose,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    if result.returncode != 0:
        print(f"FAILED (exit {result.returncode})", file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip()[-1000:], file=sys.stderr)
        return result.returncode

    if not verbose:
        tail = (result.stdout or "")[-500:].strip()
        if tail:
            print(tail)
    return 0


def _create_venv(dry_run: bool, verbose: bool) -> Path | None:
    venv_dir = PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}-venv"
    if venv_dir.exists():
        print(f"Venv already exists at {venv_dir} - skipping creation")
        return venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"

    if dry_run:
        print(f"[dry-run] Would create venv at {venv_dir}")
        return None

    import venv
    if verbose:
        print(f"Creating venv at {venv_dir} ...")
    builder = venv.EnvBuilder(with_pip=True, symlinks=os.name != "nt")
    builder.create(str(venv_dir))
    print(f"Venv created at {venv_dir}")
    return venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Developer install/update for Custodian Kernel",
    )
    parser.add_argument(
        "--mode", choices=MODES, default="editable",
        help=f"Install mode (default: editable). Choices: {', '.join(MODES)}",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print actions without executing them",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show pip output in real time",
    )
    parser.add_argument(
        "--print-pip-cmd", action="store_true", dest="print_cmd",
        help="Print the equivalent pip command and exit",
    )
    args = parser.parse_args()

    if args.print_cmd:
        print(_pip_cmd(args.mode))
        return 0

    print(f"[dev-install] mode={args.mode}"
          f"{' dry-run' if args.dry_run else ''}"
          f"{' verbose' if args.verbose else ''}")

    if args.mode == "fresh":
        py = _create_venv(args.dry_run, args.verbose)
        if py is None and not args.dry_run:
            return 0
    else:
        py = Path(sys.executable)

    exit_code = _run_pip(args.mode, args.verbose, args.dry_run)
    if exit_code != 0:
        return exit_code

    if not args.dry_run and args.mode != "fresh":
        if _check_installed():
            print("Package is importable - install looks correct")
        else:
            print("Warning: package not importable after install", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
