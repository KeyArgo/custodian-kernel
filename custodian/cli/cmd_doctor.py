"""Health checks for a Custodian installation and its optional integrations."""
from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _plugin_enabled(lines: list[str], name: str) -> bool:
    """Return True if ``name`` appears as an enabled plugin in the output
    of ``hermes plugins list --plain --no-bundled``."""
    return any(
        line.split()[-1:] == [name] and line.split()[:1] == ["enabled"]
        for line in lines
    )


def _hermes_interpreter() -> str | None:
    """Return the Python interpreter Hermes Agent runs under, or None.

    Reads the shebang of the ``hermes`` CLI if it's a text script; for
    compiled / wrapped launchers (PyInstaller, Go shim, …) returns None
    so the caller can skip interpreter-sensitive checks rather than
    guessing.
    """
    hermes_bin = shutil.which("hermes")
    if not hermes_bin or not os.access(hermes_bin, os.R_OK):
        return None
    try:
        top = Path(hermes_bin).read_bytes()[:256]
        if not top.startswith(b"#!"):
            return None
        parts = top.decode("utf-8", errors="replace").strip().split(maxsplit=1)
        return parts[0][2:] or None
    except OSError:
        return None


def _venv_prefix(interpreter: str) -> str | None:
    """Return sys.prefix for `interpreter`, or None if we can't ask it."""
    try:
        result = subprocess.run(
            [interpreter, "-c", "import sys; print(sys.prefix)"],
            capture_output=True, text=True, timeout=5,
        )
        prefix = result.stdout.strip()
        return prefix if result.returncode == 0 and prefix else None
    except Exception:
        return None


def _verify_guard_enforcement(hermes_home: Path) -> tuple[bool, str]:
    """Smoke-test that the custodian-hermes-guard plugin's Python runtime
    is importable and its hooks register correctly.  Returns (ok, message).

    This is a best-effort check: it imports the bundled kernel plugin, not
    the deployed copy (the deployed-copy *presence* is already checked via
    the filesystem check), because the kernel's packaged code is what the
    deployed copy imports from.  If the kernel module loads and registers
    both hooks, the enforcement wiring is intact.
    """
    try:
        from custodian.hermes_guard import plugin as guard_plugin
    except Exception as exc:
        return False, f"guard plugin module failed to import: {exc}"

    ctx = _MockPluginContext()
    try:
        guard_plugin.register(ctx)
    except Exception as exc:
        return False, f"guard plugin register() failed: {exc}"

    required = {"pre_tool_call", "transform_tool_result"}
    missing = required - set(ctx.hooks)
    if missing:
        return False, f"guard plugin is missing hooks: {', '.join(sorted(missing))}"
    return True, "guard plugin hooks are wired and importable"


class _MockPluginContext:
    """Minimal stand-in for Hermes' PluginContext."""
    def __init__(self):
        self.hooks: dict[str, object] = {}

    def register_hook(self, name, fn):
        self.hooks[name] = fn


def _hermes_home() -> Path:
    """Resolve the active Hermes profile dir (where plugins actually live).

    Prefers HERMES_HOME, then the active-profile layout, then the plain
    default. Deliberately duplicated from talaria.cli._hermes_home() rather
    than imported: custodian-kernel must never depend on talaria (see
    tests/test_architecture_boundaries.py) -- this command has to run, and
    report "Talaria is not installed" correctly, even when talaria isn't
    installed at all. Keep the two in sync by hand if either changes.

    Hermes supports multiple named profiles, each with its own plugin
    directory (~/.hermes/profiles/<name>/plugins/, not ~/.hermes/plugins/
    directly) -- checking only the bare default falsely reports an
    installed, enabled plugin as missing on any profile-based install.
    """
    configured = os.environ.get("HERMES_HOME")
    if configured:
        return Path(configured).expanduser()
    base = Path.home() / ".hermes"
    active = base / "active_profile"
    if active.exists():
        name = active.read_text().strip()
        # A profile name is a single path segment, never a path itself --
        # see talaria.cli._hermes_home()'s matching comment for why this
        # guards against active_profile contents redirecting outside
        # ~/.hermes entirely.
        if name and os.sep not in name and "/" not in name and name not in ("..", "."):
            candidate = base / "profiles" / name
            if candidate.is_dir():
                return candidate
    return base


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
        print(f"\u2713 kernel import works ({kernel_version or 'source checkout'})")
    except Exception as exc:
        failures.append(f"kernel import failed: {exc}")
        print(f"\u2717 {failures[-1]}")

    try:
        if importlib.util.find_spec("paladin") is None:
            raise RuntimeError("Paladin package is missing")
        if importlib.util.find_spec("cryptography.hazmat.primitives.ciphers.aead") is None:
            raise RuntimeError("cryptography AES-GCM support is unavailable")
        print("\u2713 Paladin and its cryptography dependency are available")
    except Exception as exc:
        failures.append(f"Paladin is unavailable: {exc}")
        print(f"\u2717 {failures[-1]}")

    hermes_command = shutil.which("hermes")
    hermes_home = _hermes_home()
    hermes_detected = bool(hermes_command or hermes_home.exists())
    print(f"{'\u2713' if hermes_detected else '\u2022'} Hermes Agent detected: "
          f"{'yes' if hermes_detected else 'no'}")

    # Confined execution is deliberately opt-in: its absence must not make a
    # normal installation unhealthy, but someone selecting the mode needs an
    # unambiguous readiness answer before a tool invocation is authorized.
    confined_requested = os.environ.get("CUSTODIAN_EXECUTION_MODE", "").lower() == "confined"
    try:
        from custodian.sandbox import confined_sandbox_available
        confined_ready = confined_sandbox_available()
    except Exception:
        confined_ready = False
    if confined_ready:
        print("\u2713 Confined execution: Bubblewrap no-network profile is ready")
    else:
        message = "Confined execution is unavailable (Bubblewrap or unprivileged namespaces)"
        print(f"{'\u2717' if confined_requested else '\u2022'} {message}")
        if confined_requested:
            failures.append(message)

    talaria_spec = importlib.util.find_spec("talaria")
    talaria_version = _distribution_version("custodian-talaria")
    if talaria_spec is None:
        message = "Talaria is not installed"
        print(f"{'\u2717' if require_hermes else '\u2022'} {message}")
        if require_hermes:
            failures.append(message)
    else:
        print(f"\u2713 Talaria import works ({talaria_version or 'source checkout'})")

    if require_hermes:
        _guard_enabled = False
        _talaria_enabled = False
        hermes_interpreter = _hermes_interpreter()
        hermes_prefix = _venv_prefix(hermes_interpreter) if hermes_interpreter else None
        if hermes_interpreter is None or hermes_prefix is None:
            print("\u2022 Could not verify which Python interpreter Hermes Agent runs "
                  "under (unrecognized launcher) -- the checks below may pass "
                  "even if the plugin isn't actually importable inside Hermes.")
        elif hermes_prefix != sys.prefix:
            message = (
                f"custodian is running under {sys.prefix}, but Hermes Agent runs "
                f"under {hermes_prefix} -- a plugin installed here is invisible "
                f"to Hermes even though the checks below may still pass. "
                f"Reinstall with: {hermes_interpreter} -m pip install custodian-kernel "
                f"&& {hermes_interpreter} -m custodian.cli.main setup --profile hermes --enable"
            )
            failures.append(message)
            print(f"\u2717 {message}")
        else:
            print(f"\u2713 Running under Hermes's own interpreter ({hermes_interpreter})")

        talaria_plugin = hermes_home / "plugins" / "talaria-guard" / "plugin.yaml"
        hermes_guard_plugin = hermes_home / "plugins" / "custodian-hermes-guard" / "plugin.yaml"
        talaria_home = Path(os.environ.get("TALARIA_HOME", str(Path.home() / ".talaria"))).expanduser()
        policy = talaria_home / "policy.yaml"
        for label, path in (("Hermes plugin (talaria)", talaria_plugin),
                             ("Hermes guard plugin (custodian)", hermes_guard_plugin),
                             ("Talaria policy", policy)):
            if path.exists():
                print(f"\u2713 {label}: {path}")
            else:
                failures.append(f"{label} is missing: {path}")
                print(f"\u2717 {failures[-1]}")
        if hermes_command:
            check = subprocess.run(
                [hermes_command, "plugins", "list", "--plain", "--no-bundled"],
                capture_output=True,
                text=True,
            )
            if check.returncode != 0:
                failures.append(
                    f"`hermes plugins list` failed (exit {check.returncode}): "
                    f"{check.stderr.strip() or 'no output'}"
                )
                print(f"\u2717 {failures[-1]}")
            else:
                lines = check.stdout.splitlines()
                _guard_enabled = _plugin_enabled(lines, "custodian-hermes-guard")
                _talaria_enabled = _plugin_enabled(lines, "talaria-guard")
                if _talaria_enabled:
                    print("\u2713 Hermes plugin (talaria) is enabled")
                else:
                    failures.append("Hermes plugin (talaria) is installed but not enabled")
                    print(f"\u2717 {failures[-1]}")
                if _guard_enabled:
                    print("\u2713 Hermes guard plugin (custodian) is enabled")
                elif hermes_guard_plugin.exists():
                    failures.append("Hermes guard plugin (custodian) is installed but not enabled")
                    print(f"\u2717 {failures[-1]}")
                # else: plugin missing — already reported above

        # Enforcement verification: prove the guard runtime actually works.
        ok, msg = _verify_guard_enforcement(hermes_home)
        if ok:
            print(f"\u2713 Enforcement verified: {msg}")
        else:
            failures.append(f"Enforcement check failed: {msg}")
            print(f"\u2717 {failures[-1]}")

        # Restart advisory: an enabled plugin needs a fresh session.
        if _guard_enabled or _talaria_enabled:
            print("\u2139\ufe0f  If a Hermes session is already running, restart it — "
                  "plugins take effect on the next session, not the current one.")

    if failures:
        print("\nNot ready:")
        for failure in failures:
            print(f"  - {failure}")
        print("Run `custodian setup --profile hermes` to repair a Hermes installation.")
        return 1

    print("\nReady. Custodian's installed components passed their health checks.")
    return 0
