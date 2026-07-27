#!/usr/bin/env python3
"""Custodian Safe Release — preparation controller.

Usage:
    custodian-release.py prepare <component> <version>
    custodian-release.py prepare --all <version>

This script implements the PREPARATION side of RELEASE_SAFETY_PLAN.md.
It builds, hashes, installs, and tests release candidates. It NEVER
commits, pushes, tags, creates GitHub releases, or uploads to PyPI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
from pathlib import Path

# ---------------------------------------------------------------------------
# Component registry
# ---------------------------------------------------------------------------

COMPONENT_REGISTRY: dict[str, dict] = {
    "kernel": {
        "package": "custodian-kernel",
        "repo": "KeyArgo/custodian-kernel",
        "has_paladin": True,
        "build_script": "scripts/build-kernel-release-tree.py",
        "pyproject_template": "packaging/kernel/pyproject.toml",
    },
    "codex-guard": {
        "package": "custodian-codex-guard",
        "repo": "KeyArgo/custodian-codex-guard",
        "build_script": "scripts/build-codex-guard-release-tree.py",
        "pyproject_template": "packaging/codex_guard/pyproject.toml",
    },
    "talaria": {
        "package": "custodian-talaria",
        "repo": "KeyArgo/talaria",
    },
}

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PRIVATE_ROOT = Path(__file__).resolve().parents[1]
_RELEASE_MANIFESTS = _PRIVATE_ROOT / "release-manifests"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMPONENT_NAMES = sorted(COMPONENT_REGISTRY)


def _checked(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    if any(not isinstance(c, str) for c in cmd):
        raise TypeError("all command arguments must be strings")
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print(f"COMMAND FAILED (exit {result.returncode}): {' '.join(cmd)}", file=sys.stderr)
        if result.stdout:
            print(result.stdout.strip()[-2000:], file=sys.stderr)
        if result.stderr:
            print(result.stderr.strip()[-2000:], file=sys.stderr)
        raise SystemExit(result.returncode)
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit(path: Path) -> str:
    return _checked(["git", "rev-parse", "HEAD"], cwd=path).stdout.strip()


def _git_tree_hash(path: Path) -> str:
    return _checked(["git", "rev-parse", "HEAD:"], cwd=path).stdout.strip()


def _git_is_dirty(path: Path) -> bool:
    return bool(_checked(["git", "status", "--porcelain"], cwd=path).stdout.strip())


def _content_digest(tree: Path) -> str:
    """Deterministic SHA-256 of every file in *tree* sorted by relative path."""
    h = hashlib.sha256()
    for path in sorted(tree.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(tree)
        h.update(str(rel).encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Public-repo path resolution
# ---------------------------------------------------------------------------

def _resolve_public_repo_path(component: str) -> Path | None:
    mapping = {
        "kernel": Path("/mnt/homes/Development/custodian-kernel"),
        "codex-guard": Path("/mnt/homes/Development/custodian-codex-guard"),
    }
    explicit = mapping.get(component)
    if explicit is not None and explicit.is_dir():
        return explicit.resolve()
    if component == "talaria":
        talaria_candidates = [
            Path("/mnt/homes/Development/talaria"),
            Path("/mnt/homes/Development/KeyArgo/talaria"),
            Path.home() / "talaria",
        ]
        for candidate in talaria_candidates:
            if candidate.is_dir():
                pyproj = candidate / "pyproject.toml"
                if pyproj.is_file():
                    return candidate.resolve()
    return None


def _extract_pyproject_version(pyproject_path: Path) -> str | None:
    try:
        text = pyproject_path.read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        if m:
            return m.group(1)
        try:
            import tomllib
            data = tomllib.loads(text)
        except (ImportError, Exception):
            data = json.loads(text) if text.lstrip().startswith("{") else None
        if data and "project" in data:
            return data["project"].get("version")
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Build the filtered public source tree
# ---------------------------------------------------------------------------

def _build_public_tree(component: str, work_dir: Path) -> Path:
    info = COMPONENT_REGISTRY[component]
    builder = info.get("build_script")
    if builder:
        builder_path = _PRIVATE_ROOT / builder
        tree = work_dir / "release-tree"
        _checked([sys.executable, str(builder_path), str(tree)])
        return tree
    if component == "talaria":
        source = _resolve_public_repo_path("talaria")
        if source is None:
            raise ValueError("Talaria checkout not found")
        tree = work_dir / "release-tree"
        shutil.copytree(
            source, tree,
            ignore=shutil.ignore_patterns(
                ".git", ".pytest_cache", ".coverage", "dist", "build",
                "*.egg-info", "__pycache__", "*.pyc",
            ),
        )
        return tree
    raise ValueError(f"no build routine for component: {component}")


# ---------------------------------------------------------------------------
# Build wheel and sdist (once)
# ---------------------------------------------------------------------------

def _build_artifacts(tree: Path, dist_dir: Path) -> tuple[Path, Path | None]:
    _checked([sys.executable, "-m", "build", "--wheel", "-o", str(dist_dir), str(tree)])
    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        print("ERROR: no wheel produced by build", file=sys.stderr)
        raise SystemExit(1)
    wheel = wheels[0]

    _checked([sys.executable, "-m", "build", "--sdist", "-o", str(dist_dir), str(tree)])
    sdists = list(dist_dir.glob("*.tar.gz"))
    sdist = sdists[0] if sdists else None
    return wheel, sdist


def _extract_wheel_version(wheel: Path) -> str:
    import zipfile
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if name.endswith("METADATA") and not name.startswith(".whl"):
                try:
                    text = zf.read(name).decode("utf-8")
                    m = re.search(r"^Version:\s*(\S+)", text, re.MULTILINE)
                    if m:
                        return m.group(1).strip()
                except Exception:
                    continue
    raise ValueError(f"could not extract version from wheel: {wheel}")


# ---------------------------------------------------------------------------
# Record artifact details
# ---------------------------------------------------------------------------

def _record_artifacts(dist_dir: Path) -> list[dict]:
    artifacts = []
    for path in sorted(dist_dir.iterdir()):
        if path.is_file() and (path.suffix in (".whl", ".tar.gz") or path.name.endswith(".tar.gz")):
            artifacts.append({
                "name": path.name,
                "path": str(path.relative_to(dist_dir)),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            })
    return artifacts


def _prepared_kernel_wheel() -> Path:
    """Return the hash-verified kernel candidate required by integrations."""
    version = os.environ.get("CUSTODIAN_RELEASE_KERNEL_VERSION", "0.4.1")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("CUSTODIAN_RELEASE_KERNEL_VERSION must be an exact X.Y.Z version")
    component_dir = _RELEASE_MANIFESTS / f"kernel-{version}"
    manifest_path = component_dir / f"kernel-{version}.manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(
            f"kernel {version} must be prepared before Codex Guard or Talaria"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    wheels = [item for item in manifest["artifacts"] if item["name"].endswith(".whl")]
    if len(wheels) != 1:
        raise SystemExit("kernel preparation manifest must contain exactly one wheel")
    wheel = component_dir / "artifacts" / wheels[0]["name"]
    if not wheel.is_file() or _sha256(wheel) != wheels[0]["sha256"]:
        raise SystemExit("prepared kernel wheel is missing or its hash changed")
    return wheel


def _install_candidate(pip: Path, component: str, wheel: Path) -> None:
    if component != "kernel":
        _checked([str(pip), "install", "--quiet", str(_prepared_kernel_wheel())], timeout=300)
    _checked([str(pip), "install", "--quiet", str(wheel)], timeout=300)


# ---------------------------------------------------------------------------
# Discover latest lower PyPI version
# ---------------------------------------------------------------------------

def _discover_latest_pypi_version(package: str, current_version: str) -> str | None:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"WARNING: could not fetch PyPI versions for {package}: {exc}", file=sys.stderr)
        return None
    releases = data.get("releases", {})
    published = [
        v for v in releases.keys()
        if any(rel.get("packagetype") in ("bdist_wheel", "sdist") for rel in releases[v])
    ]
    def version_key(value: str) -> tuple[int, ...]:
        if not re.fullmatch(r"\d+(?:\.\d+)*", value):
            return ()
        return tuple(int(part) for part in value.split("."))

    current_key = version_key(current_version)
    lower = [v for v in published if version_key(v) and version_key(v) < current_key]
    if not lower:
        print(f"ERROR: no published PyPI version lower than {current_version} for {package}", file=sys.stderr)
        return None
    lower.sort(key=version_key)
    return lower[-1]


# ---------------------------------------------------------------------------
# Fresh install test (isolated venv)
# ---------------------------------------------------------------------------

def _smoke_test(component: str, bin_dir: Path) -> dict:
    result = {"test": "smoke", "passed": False, "checks": {}}
    ext = ".exe" if os.name == "nt" else ""

    if component == "kernel":
        custodian = bin_dir / f"custodian{ext}"
        ver = _checked([str(custodian), "--version"], timeout=30).stdout.strip()
        result["checks"]["custodian --version"] = ver

        paladin = bin_dir / f"paladin{ext}"
        paladin_out = _checked([str(paladin), "--help"], timeout=30).stdout.strip()
        result["checks"]["paladin --help"] = "usage:" in paladin_out
        health = _checked([
            str(custodian), "health", "--format", "json", "--state-dir",
            str(bin_dir.parent / "health-state"),
        ], timeout=30)
        health_data = json.loads(health.stdout)
        result["checks"]["custodian health"] = health_data.get("status") == "pass"

        result["passed"] = all(bool(value) for value in result["checks"].values())

    elif component == "codex-guard":
        codex = bin_dir / f"custodian-codex{ext}"
        help_out = _checked([str(codex), "--help"], timeout=30).stdout.strip()
        result["checks"]["custodian-codex --help"] = "usage:" in help_out.lower()
        mcp = bin_dir / f"custodian-codex-guard-mcp{ext}"
        request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }) + "\n"
        handshake = subprocess.run(
            [str(mcp)],
            input=request,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if handshake.returncode != 0:
            raise RuntimeError(
                f"installed MCP server failed ({handshake.returncode}): "
                f"{handshake.stderr.strip()}"
            )
        response = json.loads(handshake.stdout.strip())
        server_info = response.get("result", {}).get("serverInfo", {})
        result["checks"]["MCP initialize handshake"] = (
            response.get("id") == 1
            and server_info.get("name") == "custodian-codex-guard"
        )
        installed_version = _checked([
            str(bin_dir / f"python{ext}"), "-c",
            "import importlib.metadata as m; print(m.version('custodian-codex-guard'))",
        ], timeout=15).stdout.strip()
        result["checks"]["MCP version matches installed distribution"] = (
            server_info.get("version") == installed_version
        )
        result["passed"] = all(bool(value) for value in result["checks"].values())

    elif component == "talaria":
        talaria = bin_dir / f"talaria{ext}"
        help_out = _checked([str(talaria), "--help"], timeout=30).stdout.strip()
        result["checks"]["talaria --help"] = "usage:" in help_out.lower()

        import_check = _checked([
            str(bin_dir / f"python{ext}"), "-c", "import talaria; print(talaria.__name__)",
        ], timeout=15).stdout.strip()
        result["checks"]["import talaria"] = import_check == "talaria"

        result["passed"] = all(bool(value) for value in result["checks"].values())

    return result


def _test_fresh_install(component: str, wheel: Path, work_dir: Path) -> dict:
    result = {"test": "fresh-install", "passed": False}
    env_dir = work_dir / "venv-fresh"
    venv.create(env_dir, with_pip=True)
    bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    pip = bin_dir / ("pip.exe" if os.name == "nt" else "pip")
    _install_candidate(pip, component, wheel)

    smoke = _smoke_test(component, bin_dir)
    if smoke["passed"]:
        result["version"] = str(smoke["checks"].get(next(iter(smoke["checks"])), ""))
        result["smoke"] = smoke
        result["passed"] = True
    return result


# ---------------------------------------------------------------------------
# Upgrade-from-PyPI test
# ---------------------------------------------------------------------------

def _test_upgrade_from_pypi(component: str, wheel: Path, work_dir: Path) -> dict:
    result = {"test": "upgrade-from-pypi", "passed": False}
    package = COMPONENT_REGISTRY[component]["package"]

    version_from_wheel = _extract_wheel_version(wheel)
    prev_version = _discover_latest_pypi_version(package, version_from_wheel)
    if prev_version is None:
        result["reason"] = "no lower PyPI version found"
        return result

    env_dir = work_dir / "venv-upgrade"
    venv.create(env_dir, with_pip=True)
    bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    pip = bin_dir / ("pip.exe" if os.name == "nt" else "pip")

    _checked([str(pip), "install", f"{package}=={prev_version}"], timeout=300)
    if component != "kernel":
        _checked([
            str(pip), "install", "--upgrade", str(_prepared_kernel_wheel())
        ], timeout=300)
    _checked([str(pip), "install", "--upgrade", str(wheel)], timeout=300)

    smoke = _smoke_test(component, bin_dir)
    if smoke["passed"]:
        result["version"] = str(smoke["checks"].get(next(iter(smoke["checks"])), ""))
        result["smoke"] = smoke
        result["upgraded_from"] = prev_version
        result["passed"] = True
    return result


# ---------------------------------------------------------------------------
# Managed install (two-slot reinstall / uninstall)
# ---------------------------------------------------------------------------

def _test_managed_install(component: str, wheel: Path, work_dir: Path) -> dict:
    result = {"test": "managed-install", "passed": False}
    if component not in ("kernel",):
        result["not_applicable"] = f"managed install not applicable for {component}"
        result["passed"] = True
        return result

    managed = work_dir / "managed"
    commands = work_dir / "commands"
    commands.mkdir(exist_ok=True)
    installer = _PRIVATE_ROOT / "scripts/install-custodian.py"
    home = work_dir / "home"

    markers = [
        home / ".custodian/vaults/KEEP",
        home / ".paladin/KEEP",
        home / ".talaria/KEEP",
    ]
    marker_content = b"preserve\x00data"
    for marker in markers:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(marker_content)

    env = dict(os.environ, HOME=str(home))
    env.pop("PYTHONPATH", None)

    _checked([
        sys.executable, str(installer), "--package", str(wheel),
        "--runtime-root", str(managed), "--bin-dir", str(commands),
    ], env=env, timeout=300)

    ext = ".exe" if os.name == "nt" else ""
    custodian_cmd = commands / f"custodian{ext}"
    version_out = _checked([str(custodian_cmd), "--version"], env=env, timeout=30).stdout.strip()
    result["version"] = version_out
    health_out = _checked([
        str(custodian_cmd), "health", "--format", "json", "--state-dir",
        str(home / ".custodian"),
    ], env=env, timeout=30).stdout
    health = json.loads(health_out)
    if not (health.get("installation_proof") or {}).get("valid"):
        return result
    result["installation-proof-valid"] = True

    _checked([
        sys.executable, str(installer), "--package", str(wheel),
        "--runtime-root", str(managed), "--bin-dir", str(commands),
    ], env=env, timeout=300)
    version_out = _checked([str(custodian_cmd), "--version"], env=env, timeout=30).stdout.strip()
    result["version-after-reinstall"] = version_out

    _checked([
        sys.executable, str(installer), "--runtime-root", str(managed),
        "--bin-dir", str(commands), "--uninstall",
    ], env=env, timeout=30)
    result["uninstall-done"] = True

    for marker in markers:
        actual = marker.read_bytes()
        assert actual == marker_content, f"data marker not preserved byte-identical: {marker}"
    result["data-preserved"] = True

    wheel_hash = _sha256(wheel)
    runtime_hash_file = managed.with_name(managed.name + ".removed") / "release-artifact.sha256"
    if not runtime_hash_file.exists():
        return result
    stored_hash = runtime_hash_file.read_text(encoding="utf-8").strip()
    result["wheel-hash-stored"] = stored_hash
    result["wheel-hash-verified"] = stored_hash == wheel_hash
    result["passed"] = result["wheel-hash-verified"]
    return result


# ---------------------------------------------------------------------------
# PEP 668 compliance
# ---------------------------------------------------------------------------

def _test_pep668_compliance(component: str, wheel: Path, work_dir: Path) -> dict:
    result = {"test": "pep668-compliance", "passed": False}
    if component != "kernel":
        result["not_applicable"] = f"PEP 668 only applies to kernel managed installer"
        result["passed"] = True
        return result

    env_dir = work_dir / "venv-pep668"
    venv.create(env_dir, with_pip=True)
    bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")

    ext = ".exe" if os.name == "nt" else ""
    pip = bin_dir / f"pip{ext}"

    env = dict(os.environ, PIP_REQUIRE_VIRTUALENV="true")

    managed = work_dir / "managed-pep"
    commands = work_dir / "commands-pep"
    commands.mkdir(exist_ok=True)
    installer = _PRIVATE_ROOT / "scripts/install-custodian.py"
    home = work_dir / "home-pep"

    for d in [home / ".custodian/vaults", home / ".paladin", home / ".talaria"]:
        d.mkdir(parents=True, exist_ok=True)

    env_managed = dict(os.environ, HOME=str(home), PIP_REQUIRE_VIRTUALENV="true")
    env_managed.pop("PYTHONPATH", None)

    _checked([
        sys.executable, str(installer), "--package", str(wheel),
        "--runtime-root", str(managed), "--bin-dir", str(commands),
    ], env=env_managed, timeout=300)
    result["managed-installer-succeeded-under-pip-require-virtualenv"] = True

    _checked([
        sys.executable, str(installer), "--runtime-root", str(managed),
        "--bin-dir", str(commands), "--uninstall",
    ], env=env_managed, timeout=30)
    result["managed-uninstall-succeeded"] = True

    source = installer.read_text(encoding="utf-8")
    assert "--user" not in source, "managed installer must not use --user flag"
    assert "--break-system-packages" not in source, "managed installer must not use --break-system-packages"
    result["no-user-flag"] = True
    result["no-break-system-packages-flag"] = True

    result["passed"] = True
    return result


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def _write_manifest(
    component: str, version: str, work_dir: Path,
    results: list[dict], artifacts: list[dict],
    tree: Path, tree_hash: str | None,
    wheel: Path | None, sdist: Path | None,
) -> Path:
    component_dir = _RELEASE_MANIFESTS / f"{component}-{version}"
    manifest_dir = component_dir / "artifacts"
    manifest_dir.mkdir(parents=True, exist_ok=True)

    if wheel and wheel.is_file():
        shutil.copy2(wheel, manifest_dir / wheel.name)
    if sdist and sdist.is_file():
        shutil.copy2(sdist, manifest_dir / sdist.name)

    component_info = dict(COMPONENT_REGISTRY[component])

    manifest = {
        "component": component,
        "package": component_info["package"],
        "version": version,
        "public_repo": component_info["repo"],
        "intended_tag": f"v{version}",
        "private_source_commit": _git_commit(_PRIVATE_ROOT),
        "content_digest": tree_hash,
        "prepared_at": time.time(),
        "prepared_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "artifacts": artifacts,
        "test_results": results,
        "all_tests_passed": all(r.get("passed", False) for r in results),
        "note": "PREPARATION ONLY. This manifest describes a candidate that has NOT been published.",
    }

    manifest_path = component_dir / f"{component}-{version}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def _write_report(
    component: str, version: str, results: list[dict],
    artifacts: list[dict], manifest_path: Path,
) -> Path:
    component_dir = _RELEASE_MANIFESTS / f"{component}-{version}"
    report_path = component_dir / f"{component}-{version}.report.txt"

    lines = [
        f"Custodian Release Preparation Report",
        f"====================================",
        f"Component: {component}",
        f"Version:   {version}",
        f"Time:      {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        f"Artifacts:",
    ]
    for a in artifacts:
        lines.append(f"  {a['name']}")
        lines.append(f"    path: {a['path']}")
        lines.append(f"    size: {a['size']}")
        lines.append(f"    SHA-256: {a['sha256']}")
    lines.append("")
    lines.append("Test Results:")
    for r in results:
        status = (
            "N/A" if "not_applicable" in r
            else "PASS" if r.get("passed")
            else "FAIL"
        )
        lines.append(f"  [{status}] {r['test']}")
        if "not_applicable" in r:
            lines.append(f"           {r['not_applicable']}")

    all_ok = all(r.get("passed", False) for r in results)
    lines.append("")
    lines.append(f"Overall: {'ALL TESTS PASSED' if all_ok else 'SOME TESTS FAILED'}")
    lines.append("")
    lines.append(f"Manifest: {manifest_path}")
    lines.append("")
    lines.append("This is a PREPARATION report. No packages were published.")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# Prepare command
# ---------------------------------------------------------------------------

def _cmd_prepare(component: str, version: str) -> int:
    if component not in COMPONENT_REGISTRY:
        print(f"Unknown component: {component}. Choices: {', '.join(_COMPONENT_NAMES)}", file=sys.stderr)
        return 1

    info = COMPONENT_REGISTRY[component]
    package = info["package"]
    public_repo = info["repo"]

    public_path = _resolve_public_repo_path(component)
    if public_path is not None:
        if _git_is_dirty(public_path):
            print(f"ERROR: public repo {public_path} has uncommitted changes. Refusing to prepare from dirty checkout.", file=sys.stderr)
            return 1
        actual_remote = _checked(["git", "remote", "get-url", "origin"], cwd=public_path).stdout.strip()
        for allowed_pattern in [f"github.com/{public_repo}", f"github.com/{public_repo}.git"]:
            if allowed_pattern in actual_remote:
                break
        else:
            print(f"ERROR: public repo {public_path} remote {actual_remote} does not match {public_repo}", file=sys.stderr)
            return 1

        if component == "talaria":
            pyproject_file = public_path / "pyproject.toml"
            if pyproject_file.is_file():
                pyproject_ver = _extract_pyproject_version(pyproject_file)
                if pyproject_ver is not None and pyproject_ver != version:
                    print(f"ERROR: requested version {version} does not match pyproject.toml version {pyproject_ver}", file=sys.stderr)
                    return 1

    print(f"Custodian Release — PREPARE")
    print(f"===========================")
    print(f"Component:     {component}")
    print(f"Package:       {package}")
    print(f"Version:       {version}")
    print(f"Public repo:   {public_repo}")
    print(f"Intended tag:  v{version}")
    print()

    work_dir = Path(tempfile.mkdtemp(prefix=f"custodian-release-{component}-"))

    results: list[dict] = []

    tree = _build_public_tree(component, work_dir)
    print(f"[1/9] Public tree built: {tree}")
    tree_hash = _content_digest(tree)
    print(f"[1/9] Content digest: {tree_hash[:16]}...")

    dist_dir = work_dir / "dist"
    dist_dir.mkdir(exist_ok=True)
    wheel, sdist = _build_artifacts(tree, dist_dir)
    print(f"[2/9] Wheel: {wheel}")
    if sdist:
        print(f"[2/9] Sdist: {sdist}")
    metadata_targets = [str(wheel)]
    if sdist is not None:
        metadata_targets.append(str(sdist))
    _checked(
        [sys.executable, "-m", "twine", "check", "--strict", *metadata_targets],
        timeout=60,
    )
    print("[2/9] PyPI metadata/rendering check: PASS")

    wheel_version = _extract_wheel_version(wheel)
    if wheel_version != version:
        print(f"ERROR: requested version {version} does not match built wheel version {wheel_version}", file=sys.stderr)
        shutil.rmtree(work_dir)
        return 1
    print(f"[2/9] Built version matches: {wheel_version}")

    artifacts = _record_artifacts(dist_dir)
    print(f"[3/9] Artifacts recorded: {len(artifacts)}")

    print(f"[4/9] Testing fresh install...")
    fresh_result = _test_fresh_install(component, wheel, work_dir)
    results.append(fresh_result)
    print(f"      {'PASS' if fresh_result.get('passed') else 'FAIL'}: fresh install")

    print(f"[5/9] Testing upgrade from PyPI...")
    upgrade_result = _test_upgrade_from_pypi(component, wheel, work_dir)
    results.append(upgrade_result)
    print(f"      {'PASS' if upgrade_result.get('passed') else 'SKIP' if 'skipped' in upgrade_result else 'FAIL'}: upgrade from PyPI")

    print(f"[6/9] Testing managed (two-slot) install...")
    managed_result = _test_managed_install(component, wheel, work_dir)
    results.append(managed_result)
    print(f"      {'PASS' if managed_result.get('passed') else 'SKIP' if 'skipped' in managed_result else 'FAIL'}: managed reinstall/uninstall")

    print(f"[7/9] Testing PEP 668 compliance...")
    pep668_result = _test_pep668_compliance(component, wheel, work_dir)
    results.append(pep668_result)
    print(f"      {'PASS' if pep668_result.get('passed') else 'FAIL'}: PEP 668 compliance")

    print(f"[8/9] Running smoke tests...")
    ext = ".exe" if os.name == "nt" else ""
    env_dir = work_dir / "venv-fresh"
    if env_dir.exists():
        bin_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
        smoke_result = _smoke_test(component, bin_dir)
        results.append(smoke_result)
        print(f"      {'PASS' if smoke_result.get('passed') else 'FAIL'}: smoke tests")

    print(f"[9/9] Writing manifest and report...")
    manifest_path = _write_manifest(component, version, work_dir, results, artifacts, tree, tree_hash, wheel, sdist)
    report_path = _write_report(component, version, results, artifacts, manifest_path)
    print(f"      Manifest: {manifest_path}")
    print(f"      Report:   {report_path}")

    all_ok = all(r.get("passed", False) for r in results)
    if all_ok:
        print(f"\nAll tests passed. Candidate is ready for publication review.")
    else:
        print(f"\nSome tests failed. See report for details: {report_path}")
        shutil.rmtree(work_dir)
        return 1

    shutil.rmtree(work_dir)
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Custodian Safe Release — preparation controller.",
        epilog="This script implements the PREPARATION side of RELEASE_SAFETY_PLAN.md. "
               "It NEVER commits, pushes, tags, creates GitHub releases, or uploads to PyPI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="Prepare a release candidate")
    prepare.add_argument("component", choices=_COMPONENT_NAMES,
                         help="Component to prepare for release")
    prepare.add_argument("version",
                         help="Version string (e.g. 0.4.1)")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "prepare":
        return _cmd_prepare(args.component, args.version)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
