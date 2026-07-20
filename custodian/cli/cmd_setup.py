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
    "talaria": {
        "description": "Hermes Agent + NemoClaw integration — guard plugin, vault, dashboard",
        "pip_spec": "custodian-talaria[dashboard]>=0.1.0,<0.2",
    },
}

_PROFILES = {
    "hermes": ["talaria"],
    "minimal": [],
}


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
    names: set[str] = set()
    profile = getattr(args, "profile", None)
    if profile:
        if profile not in _PROFILES:
            print(f"error: unknown profile '{profile}' (choices: {', '.join(sorted(_PROFILES))})")
            raise SystemExit(1)
        names.update(_PROFILES[profile])
    with_arg = getattr(args, "with_", None)
    if with_arg:
        for raw in with_arg.split(","):
            name = raw.strip()
            if not name:
                continue
            if name not in _COMPONENTS:
                print(f"error: unknown component '{name}' (choices: {', '.join(sorted(_COMPONENTS))})")
                raise SystemExit(1)
            names.add(name)
    return sorted(names)


def _run_checked(command: list[str], label: str) -> None:
    print(f"\n$ {' '.join(command)}")
    result = subprocess.run(command)
    if result.returncode != 0:
        print(f"error: {label} failed (exit {result.returncode})")
        raise SystemExit(1)


def run(args) -> None:
    hermes_detected = _detect_hermes()

    print("Custodian setup")
    print("================")
    print(f"Hermes Agent detected: {'yes' if hermes_detected else 'no'}")

    components = _resolve_components(args)

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
        spec = _COMPONENTS[name]
        status = spec["pip_spec"] or "already included, nothing to do"
        print(f"  - {name}: {spec['description']}  [{status}]")

    if args.dry_run:
        print("\n(--dry-run: nothing installed)")
        return

    for name in components:
        pip_spec = _COMPONENTS[name]["pip_spec"]
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
            # talaria-guard only declares pre_tool_call/transform_tool_result
            # hooks -- it never needs the separate "replace a built-in tool"
            # permission -- but `hermes plugins enable` asks about that
            # permission interactively unless told not to. Without
            # --no-allow-tool-override, a one-command installer run from a
            # real terminal stops on a Y/N prompt about a permission this
            # plugin will never use.
            _run_checked(
                ["hermes", "plugins", "enable", "talaria-guard", "--no-allow-tool-override"],
                "Hermes plugin enablement",
            )
        _run_checked(
            [sys.executable, "-m", "custodian.cli.main", "doctor", "--profile", "hermes"],
            "post-install health check",
        )

    print("\nDone. Next steps:")
    print("  custodian init                   # if you haven't already — scaffolds policy.yaml + state")
    print("  custodian doctor --profile hermes # verify the complete integration")
    if "talaria" in components:
        print("  talaria dashboard                # open the local operator interface")
        if hermes_detected:
            print("\nIf a Hermes Agent session is already running, restart it —")
            print("the plugin only takes effect on the next session, not the current one.")
