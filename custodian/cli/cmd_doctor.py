"""Health checks for a Custodian installation and its optional integrations."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _hermes_home() -> Path:
    configured = os.environ.get("HERMES_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".hermes"


def run(args) -> int:
    """Print actionable checks; require optional pieces only for their profile."""
    profile = getattr(args, "profile", None)
    require_hermes = profile == "hermes"
    failures: list[str] = []

    print("Custodian doctor")
    print("================")

    kernel_version = _distribution_version("custodian-kernel")
    try:
        import custodian  # noqa: F401
        print(f"✓ kernel import works ({kernel_version or 'source checkout'})")
    except Exception as exc:
        failures.append(f"kernel import failed: {exc}")
        print(f"✗ {failures[-1]}")

    try:
        if importlib.util.find_spec("paladin") is None:
            raise RuntimeError("Paladin package is missing")
        if importlib.util.find_spec("cryptography.hazmat.primitives.ciphers.aead") is None:
            raise RuntimeError("cryptography AES-GCM support is unavailable")
        print("✓ Paladin and its cryptography dependency are available")
    except Exception as exc:
        failures.append(f"Paladin is unavailable: {exc}")
        print(f"✗ {failures[-1]}")

    hermes_command = shutil.which("hermes")
    hermes_home = _hermes_home()
    hermes_detected = bool(hermes_command or hermes_home.exists())
    print(f"{'✓' if hermes_detected else '•'} Hermes Agent detected: "
          f"{'yes' if hermes_detected else 'no'}")

    talaria_spec = importlib.util.find_spec("talaria")
    talaria_version = _distribution_version("custodian-talaria")
    if talaria_spec is None:
        message = "Talaria is not installed"
        print(f"{'✗' if require_hermes else '•'} {message}")
        if require_hermes:
            failures.append(message)
    else:
        print(f"✓ Talaria import works ({talaria_version or 'source checkout'})")

    if require_hermes:
        plugin = hermes_home / "plugins" / "talaria-guard" / "plugin.yaml"
        talaria_home = Path(os.environ.get("TALARIA_HOME", str(Path.home() / ".talaria"))).expanduser()
        policy = talaria_home / "policy.yaml"
        for label, path in (("Hermes plugin", plugin), ("Talaria policy", policy)):
            if path.exists():
                print(f"✓ {label}: {path}")
            else:
                failures.append(f"{label} is missing: {path}")
                print(f"✗ {failures[-1]}")
        if hermes_command:
            check = subprocess.run(
                [hermes_command, "plugins", "list", "--plain", "--no-bundled"],
                capture_output=True,
                text=True,
            )
            enabled = check.returncode == 0 and any(
                line.split()[-1:] == ["talaria-guard"] and line.split()[:1] == ["enabled"]
                for line in check.stdout.splitlines()
            )
            if enabled:
                print("✓ Hermes plugin is enabled")
            else:
                failures.append("Hermes plugin is installed but not enabled")
                print(f"✗ {failures[-1]}")

    if failures:
        print("\nNot ready:")
        for failure in failures:
            print(f"  - {failure}")
        print("Run `custodian setup --profile hermes` to repair a Hermes installation.")
        return 1

    print("\nReady. Custodian's installed components passed their health checks.")
    return 0
