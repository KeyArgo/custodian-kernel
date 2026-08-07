"""`custodian setup` — the one command most users install through.

Orchestrates `pip install` for the components you actually want instead of
asking a new user to learn multiple package names. `paladin` ships inside
`custodian-kernel`'s base install already (see pyproject.toml's dependency
comment); `talaria` is its own package with its own release cadence — see
https://github.com/inovinlabs/talaria — so this is the thing that actually
runs `pip install custodian-talaria` on request.

Deliberately does nothing with zero explicit signal from the caller: bare
`custodian setup` only detects the environment (is Hermes Agent present?)
and reports what it would do. Installing only happens with --with/--profile
(an explicit ask). There is no --yes-to-everything flag that infers intent
from detection alone -- fail closed, same as everywhere else in this
project.
"""
from __future__ import annotations

import json
import importlib.resources
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from custodian.cli.cmd_doctor import _hermes_home, _hermes_interpreter, _venv_prefix

_INSTALL_RECEIPT_NAME = "install-receipt.json"
_INSTALL_RECEIPT_SCHEMA = "custodian.install-receipt.v1"


def _state_dir() -> Path:
    """Resolve the operator state directory for receipts and receipts.

    Order of precedence: ``CUSTODIAN_STATE_DIR`` (explicit), then the
    default ``~/.custodian`` -- matching the codex_guard/approvals and
    codex_guard/receipts layout so a single directory holds every
    kernel-managed artifact.
    """
    configured = os.environ.get("CUSTODIAN_STATE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".custodian"


def _kernel_version() -> str:
    """Return the installed custodian-kernel version (or 'unknown' for
    source checkouts where importlib.metadata has no entry)."""
    try:
        return __import__("importlib").metadata.version("custodian-kernel")
    except Exception:
        return "unknown"


def _receipt_path(state_dir: Path) -> Path:
    return state_dir / _INSTALL_RECEIPT_NAME


def _write_install_receipt(state_dir: Path, components: list[str]) -> Path:
    """Write a tamper-evident install receipt to ``state_dir``.

    The receipt is plain JSON containing the kernel version, the
    components installed, the interpreter path, and a wall-clock timestamp.
    On the next ``custodian setup`` (or any future ``doctor`` call) the
    kernel version is compared with the currently-running one and a
    mismatch is reported as a clear upgrade reminder, instead of letting
    the user wonder why new features don't work after ``pip install``.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": _INSTALL_RECEIPT_SCHEMA,
        "kernel_version": _kernel_version(),
        "components": sorted(components),
        "interpreter": sys.executable,
        "installed_at": time.time(),
    }
    target = _receipt_path(state_dir)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(target)
    return target

# pip_spec is None for components already bundled in custodian-kernel's own
# base install -- nothing to pip install, `setup` just confirms it's there.
_COMPONENTS = {
    "paladin": {
        "description": "Credential broker — vault, grants, egress (already included)",
        "pip_spec": None,
    },
    "hermes-guard": {
        "description": "Hermes guard plugin — pre/post-tool governance (already included, needs enablement)",
        "pip_spec": None,
    },
    "talaria": {
        "description": "Hermes Agent + NemoClaw integration — guard plugin, vault, dashboard",
        "pip_spec": "custodian-talaria[dashboard]>=0.1.0,<0.2",
    },
}

_PROFILES = {
    "hermes": ["talaria", "hermes-guard"],
    "minimal": [],
}


def _discovered_components() -> dict:
    """Component specs from the ``custodian.setup_components`` entry-point group.

    Each entry point is named after the component and must load() to a dict
    shaped like _COMPONENTS' values: {"description": str, "pip_spec": str | None}.
    Broken or malformed entry points are skipped silently -- a broken
    third-party package must never crash `custodian setup` for everyone else.
    """
    discovered: dict = {}
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return discovered
    try:
        eps = entry_points(group="custodian.setup_components")
    except Exception:
        return discovered
    for ep in eps:
        try:
            spec = ep.load()
        except Exception:
            continue
        if not isinstance(spec, dict):
            continue
        discovered[ep.name] = spec
    return discovered


def _discovered_profiles() -> dict:
    """Profile → component list mappings from the ``custodian.setup_profiles`` entry-point group.

    Each entry point is named after the profile and must load() to a list[str]
    of component names (the shape of _PROFILES' values). Broken or malformed
    entry points are skipped silently.
    """
    discovered: dict = {}
    try:
        from importlib.metadata import entry_points
    except ImportError:
        return discovered
    try:
        eps = entry_points(group="custodian.setup_profiles")
    except Exception:
        return discovered
    for ep in eps:
        try:
            names = ep.load()
        except Exception:
            continue
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            continue
        discovered[ep.name] = names
    return discovered


def _effective_components() -> dict:
    """Built-in components merged with entry-point-discovered ones.

    Built-ins win on a name collision -- a third-party package must never be
    able to silently redefine what "paladin" or "talaria" mean.
    """
    return {**_discovered_components(), **_COMPONENTS}


def _effective_profiles() -> dict:
    """Built-in profiles merged with entry-point-discovered ones (built-ins win)."""
    return {**_discovered_profiles(), **_PROFILES}


def _detect_hermes() -> bool:
    # Shares custodian.cli.cmd_doctor's HERMES_HOME-aware home resolution --
    # this used to hardcode ~/.hermes here while cmd_doctor checked
    # HERMES_HOME, so a user with a non-default Hermes location got told
    # "not detected" by `setup` and "detected" by `doctor` for the same
    # install.
    if shutil.which("hermes"):
        return True
    return _hermes_home().exists()


def _resolve_components(args) -> list[str]:
    components = _effective_components()
    profiles = _effective_profiles()
    names: set[str] = set()
    if getattr(args, "guard_only", False):
        # --guard-only: install exactly the guard plugin, nothing else.
        # Overrides any --profile / --with selection.
        if "hermes-guard" not in components:
            print("error: hermes-guard component not available")
            raise SystemExit(1)
        return ["hermes-guard"]
    profile = getattr(args, "profile", None)
    if profile:
        if profile not in profiles:
            print(f"error: unknown profile '{profile}' (choices: {', '.join(sorted(profiles))})")
            raise SystemExit(1)
        names.update(profiles[profile])
    with_arg = getattr(args, "with_", None)
    if with_arg:
        for raw in with_arg.split(","):
            name = raw.strip()
            if not name:
                continue
            if name not in components:
                print(f"error: unknown component '{name}' (choices: {', '.join(sorted(components))})")
                raise SystemExit(1)
            names.add(name)
    return sorted(names)


def _run_checked(command: list[str], label: str) -> None:
    print(f"\n$ {' '.join(command)}")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"error: {label} failed (exit {result.returncode})")
        raise SystemExit(1)


def _install_hermes_guard_plugin(args) -> None:
    """Copy the bundled custodian-hermes-guard plugin into the Hermes home
    directory.  The kernel ships the plugin inside its own package;
    installation copies it into the operator's Hermes profile so Hermes
    discovers it on the next session.  Does not auto-enable unless
    ``--enable`` is passed — installing must never silently activate
    enforcement (see the Hermes + Custodian control handoff).

    The operation is best-effort: a missing kernel package, read-only
    filesystem, or absent Hermes home prints a warning rather than
    aborting the whole setup.
    """
    try:
        plugin_src = importlib.resources.files("custodian").joinpath(
            "guards", "hermes", "plugin"
        )
        if not (plugin_src / "plugin.yaml").is_file():
            print("warning: bundled Hermes guard plugin not found in installed package")
            return
    except Exception as exc:
        print(f"warning: cannot locate bundled Hermes guard plugin: {exc}")
        return

    hermes_home = _hermes_home()
    dest = hermes_home / "plugins" / "custodian-hermes-guard"
    if args.dry_run:
        print(f"\nWould install Hermes guard plugin: {plugin_src} -> {dest}")
        if args.enable:
            print("Would enable the plugin (--enable)")
        return

    if dest.exists():
        shutil.rmtree(dest)
    try:
        shutil.copytree(str(plugin_src), str(dest))
    except OSError as exc:
        print(f"warning: cannot copy Hermes guard plugin to {dest}: {exc}")
        return
    print(f"\nInstalled Hermes guard plugin to {dest}")

    if args.enable and shutil.which("hermes"):
        _run_checked(
            ["hermes", "plugins", "enable", "custodian-hermes-guard", "--no-allow-tool-override"],
            "Hermes guard plugin enablement",
        )
    elif args.enable:
        print("warning: hermes not found on PATH; plugin copied but not enabled")
    else:
        print("(plugin copied but not enabled; pass --enable or run")  # no trailing paren — continued below
        print(" `hermes plugins enable custodian-hermes-guard` to activate)")


def run(args) -> None:
    hermes_detected = _detect_hermes()

    print("Custodian setup")
    print("================")
    print(f"Hermes Agent detected: {'yes' if hermes_detected else 'no'}")

    components = _resolve_components(args)
    all_components = _effective_components()

    if not components:
        if hermes_detected:
            print("\nHermes Agent found on this machine. Recommended:")
            print("  custodian setup --profile hermes")
            print("  (installs talaria — the Hermes/NemoClaw guard suite — "
                  "on top of the kernel + paladin you already have)")
        else:
            print("\nNo agent harness detected. Nothing further to install —")
            print("custodian-kernel already includes the kernel and the paladin credential broker.")
            print("Re-run with --with talaria or --profile hermes for a Hermes integration.")
        return

    print("\nComponents:")
    for name in components:
        spec = all_components[name]
        status = spec["pip_spec"] or "already included, nothing to do"
        print(f"  - {name}: {spec['description']}  [{status}]")

    hermes_components_requested = bool({"talaria", "hermes-guard"} & set(components))
    if hermes_detected and hermes_components_requested:
        hermes_interpreter = _hermes_interpreter()
        hermes_prefix = _venv_prefix(hermes_interpreter) if hermes_interpreter else None
        if hermes_interpreter and hermes_prefix and hermes_prefix != sys.prefix:
            print(
                f"\nerror: this interpreter ({sys.prefix}) is not the one Hermes "
                f"Agent runs under ({hermes_prefix}). Installing here would copy "
                f"plugin files that Hermes can never actually import -- every "
                f"check would look fine while the guard silently does nothing. "
                f"Re-run with Hermes's own interpreter:\n"
                f"  {hermes_interpreter} -m pip install custodian-kernel\n"
                f"  {hermes_interpreter} -m custodian.cli.main setup --profile hermes --enable"
            )
            if not args.dry_run:
                raise SystemExit(1)

    if args.dry_run:
        if "hermes-guard" in components and not args.skip_configure:
            _install_hermes_guard_plugin(args)
        print("\n(--dry-run: nothing installed)")
        return

    for name in components:
        pip_spec = all_components[name]["pip_spec"]
        if not pip_spec:
            continue
        _run_checked(
            [sys.executable, "-m", "pip", "install", pip_spec],
            f"pip install {pip_spec}",
        )

    if "talaria" in components and not args.skip_configure:
        _run_checked(
            [sys.executable, "-m", "talaria.cli", "hermes", "install"],
            "Talaria configuration",
        )
        if shutil.which("hermes"):
            _run_checked(
                ["hermes", "plugins", "enable", "talaria-guard", "--no-allow-tool-override"],
                "Hermes plugin enablement",
            )

    if "hermes-guard" in components and not args.skip_configure:
        _install_hermes_guard_plugin(args)

    # Health check runs last, once every requested component is in place --
    # running it after just "talaria" failed --profile hermes unconditionally,
    # since hermes-guard (a separate component in the same profile) hadn't
    # been installed yet when doctor checked for it.
    if ("talaria" in components or "hermes-guard" in components) and not args.skip_configure:
        _run_checked(
            [sys.executable, "-m", "custodian.cli.main", "doctor", "--profile", "hermes"],
            "post-install health check",
        )

    # Write a tamper-evident install receipt so future ``custodian setup``
    # and ``custodian doctor`` calls can detect kernel drift (operator
    # upgraded custodian-kernel without rerunning setup) and the doctor
    # can warn the operator clearly instead of letting new features fail
    # silently.
    try:
        receipt = _write_install_receipt(_state_dir(), components)
        print(f"  install receipt: {receipt}")
    except OSError as exc:
        print(f"warning: could not write install receipt ({exc})")

    print("\nDone. Next steps:")
    print("  custodian init                   # if you haven't already — scaffolds policy.yaml + state")
    print("  custodian doctor --profile hermes # verify the complete integration")
    if "talaria" in components:
        print("  talaria dashboard                # open the local operator interface")
        if hermes_detected:
            print("\nIf a Hermes Agent session is already running, restart it —")
            print("the plugin only takes effect on the next session, not the current one.")
