#!/usr/bin/env python3
"""Create the exact standalone custodian-codex-guard release source tree."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_tree(output: Path) -> None:
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        ROOT / "custodian/codex_guard",
        output / "custodian/codex_guard",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    bundled = output / "custodian/codex_guard/bundled_plugin"
    shutil.copytree(ROOT / ".agents", bundled / ".agents")
    shutil.copytree(
        ROOT / "plugins/custodian-codex-guard",
        bundled / "plugins/custodian-codex-guard",
    )
    shutil.copy2(ROOT / "packaging/codex_guard/pyproject.toml", output / "pyproject.toml")
    shutil.copy2(ROOT / "packaging/codex_guard/MANIFEST.in", output / "MANIFEST.in")
    shutil.copy2(ROOT / "packaging/codex_guard/README.md", output / "README.md")
    shutil.copy2(ROOT / "LICENSE", output / "LICENSE")
    shutil.copy2(ROOT / "docs/SECURITY.md", output / "SECURITY.md")
    shutil.copy2(ROOT / "docs/CONTRIBUTING.md", output / "CONTRIBUTING.md")
    shutil.copy2(ROOT / "docs/CODE_OF_CONDUCT.md", output / "CODE_OF_CONDUCT.md")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build_tree(args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
