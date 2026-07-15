"""Package boundary guard.

custodian/ is the brand-neutral kernel + adapter framework. paladin/ is
the brand-neutral credential broker. Neither knows the other exists at
the code level -- talaria/ is the only package allowed to import both,
because integrating them for a specific agent (Hermes) is its entire
job. A future Claude/Codex integration package would sit at the same
layer as talaria, never inside custodian or paladin.

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


def _check_package_forbids(package_dir: str, forbidden: set[str]) -> list[str]:
    violations = []
    for py_file in (REPO_ROOT / package_dir).rglob("*.py"):
        if "__pycache__" in py_file.parts:
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


def test_talaria_is_the_only_integration_layer():
    # Not a violation to check for -- a sanity check that talaria/ really
    # does depend on both, so the two tests above aren't vacuously true
    # because nothing imports anything.
    imports_custodian = False
    imports_paladin = False
    for py_file in (REPO_ROOT / "talaria").rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        names = _imported_top_level_packages(py_file)
        imports_custodian = imports_custodian or "custodian" in names
        imports_paladin = imports_paladin or "paladin" in names
    assert imports_custodian, "expected at least one talaria/ file to import custodian"
    assert imports_paladin, "expected at least one talaria/ file to import paladin"
