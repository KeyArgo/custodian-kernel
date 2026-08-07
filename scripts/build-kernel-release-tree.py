#!/usr/bin/env python3
"""Create the exact standalone custodian-kernel release source tree."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"opencode_guard", "opencode-prompts"}


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in EXCLUDED or name == "__pycache__" or name.endswith(".pyc")
    }


def build_tree(output: Path) -> None:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "custodian", output / "custodian", ignore=_ignore)
    shutil.copytree(ROOT / "paladin", output / "paladin", ignore=_ignore)
    shutil.copy2(ROOT / "packaging/kernel/pyproject.toml", output / "pyproject.toml")
    shutil.copy2(ROOT / "packaging/kernel/MANIFEST.in", output / "MANIFEST.in")
    shutil.copy2(ROOT / "packaging/kernel/README.md", output / "README.md")
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    shutil.copy2(ROOT / "CHANGELOG.md", output / "CHANGELOG.md")
    shutil.copy2(ROOT / "docs/SECURITY.md", output / "SECURITY.md")
    shutil.copy2(ROOT / "docs/CONTRIBUTING.md", output / "CONTRIBUTING.md")
    shutil.copy2(ROOT / "docs/CODE_OF_CONDUCT.md", output / "CODE_OF_CONDUCT.md")
    shutil.copy2(
        ROOT / "scripts/install-custodian.py", output / "install-custodian.py"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_tree(args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
