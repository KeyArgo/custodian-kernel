#!/usr/bin/env python3
"""Create the exact standalone custodian-stripe release source tree."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name == "__pycache__" or name.endswith(".pyc")}


def build_tree(output: Path) -> None:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "custodian_stripe", output / "custodian_stripe", ignore=_ignore)
    (output / "tests").mkdir()
    shutil.copy2(
        ROOT / "tests/test_custodian_stripe_processor.py",
        output / "tests/test_custodian_stripe_processor.py",
    )
    shutil.copy2(
        ROOT / "tests/test_custodian_stripe_entry_points.py",
        output / "tests/test_custodian_stripe_entry_points.py",
    )
    shutil.copy2(ROOT / "packaging/custodian_stripe/pyproject.toml", output / "pyproject.toml")
    shutil.copy2(ROOT / "packaging/custodian_stripe/MANIFEST.in", output / "MANIFEST.in")
    shutil.copy2(ROOT / "packaging/custodian_stripe/README.md", output / "README.md")
    shutil.copy2(ROOT / "packaging/custodian_stripe/DEPLOY-CUTOVER.md", output / "DEPLOY-CUTOVER.md")
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_tree(args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
