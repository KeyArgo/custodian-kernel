"""Package boundary guard.

custodian/ is the brand-neutral kernel + adapter framework. paladin/ is
the brand-neutral credential broker. Neither knows the other exists at
the code level. Integration layers (talaria, for Hermes -- now its own
package/repo at github.com/inovinlabs/talaria, depending on this one) are
the only place allowed to import both, because integrating them for a
specific agent is that layer's entire job. A future Claude/Codex
integration package would follow the same pattern.

This is enforced here, not just documented, because "brand-neutral" is
a promise every adapter docstring in custodian/adapters/builtin/ makes
explicitly (e.g. egress_domain_guard.py: "The guard stays brand-neutral
(no paladin import)") -- a regression here would make several of those
docstrings quietly false without anything else failing.
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _imported_top_level_packages(py_file: Path) -> set[str]:
    """Every top-level package name this file imports, via `import x`,
    `import x.y`, or `from x import y` (including `from x.y import z`)."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # ignore relative imports
                names.add(node.module.split(".")[0])
    return names


# Runtime skill scripts are NOT part of the package's import graph -- they are
# sandboxed scripts loaded dynamically by the tool registry, and an integration
# skill legitimately bridges to another system (the `paladin-import` skill's
# entire job is importing into paladin). The brand-neutrality contract is about
# the kernel + adapter framework, which is exactly what this excludes.
_SKILL_TREES = {"bundled_skills", "skills"}


def _check_package_forbids(package_dir: str, forbidden: set[str]) -> list[str]:
    violations = []
    for py_file in (REPO_ROOT / package_dir).rglob("*.py"):
        parts = py_file.parts
        if "__pycache__" in parts or _SKILL_TREES & set(parts):
            continue
        hits = _imported_top_level_packages(py_file) & forbidden
        if hits:
            violations.append(f"{py_file.relative_to(REPO_ROOT)}: imports {sorted(hits)}")
    return violations


def test_custodian_never_imports_paladin_or_talaria():
    violations = _check_package_forbids("custodian", {"paladin", "talaria"})
    assert not violations, (
        "custodian/ must stay brand-neutral -- these files import a "
        "package that should only ever be reached through the adapter "
        "interface (plain config dicts), not a direct import:\n"
        + "\n".join(violations)
    )


def test_paladin_never_imports_custodian_or_talaria():
    violations = _check_package_forbids("paladin", {"custodian", "talaria"})
    assert not violations, (
        "paladin/ must stay standalone -- these files import a package "
        "that would make the credential broker depend on an integration "
        "layer or the kernel:\n" + "\n".join(violations)
    )
