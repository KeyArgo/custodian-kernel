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

import shutil
import subprocess
import sys
from pathlib import Path

from custodian.cli.cmd_doctor import _hermes_home

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
        from importlib.resources import files
        plugin_src = files("custodian").joinpath("hermes_guard", "plugin")
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
    shutil.copytree(str(plugin_src), str(dest))
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

    if args.dry_run:
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
        _run_checked(
            [sys.executable, "-m", "custodian.cli.main", "doctor", "--profile", "hermes"],
            "post-install health check",
        )

    if "hermes-guard" in components and not args.skip_configure:
        _install_hermes_guard_plugin(args)

    print("\nDone. Next steps:")
    print("  custodian init                   # if you haven't already — scaffolds policy.yaml + state")
    print("  custodian doctor --profile hermes # verify the complete integration")
    if "talaria" in components:
        print("  talaria dashboard                # open the local operator interface")
        if hermes_detected:
            print("\nIf a Hermes Agent session is already running, restart it —")
            print("the plugin only takes effect on the next session, not the current one.")
