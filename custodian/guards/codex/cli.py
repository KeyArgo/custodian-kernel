"""Human-facing control plane for Custodian Codex Guard."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
import shutil

from .approvals import ApprovalError, ApprovalStore
from .mcp_server import _state_dir
from .receipts import ReceiptChain
from . import hook_install
from . import paladin_bridge

PLUGIN_ID = "custodian-codex-guard@custodian-build-week"


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None or (Path(sys.executable).parent / name).exists()


def _repo_root() -> Path | None:
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        if (candidate / ".agents" / "plugins" / "marketplace.json").is_file():
            return candidate
    # Wheels carry a self-contained marketplace beside this module.  Setup
    # must work from any directory after ``pip install``, not only while the
    # current directory happens to be the private source checkout.
    bundled = Path(__file__).resolve().parent / "bundled_plugin"
    if (bundled / ".agents" / "plugins" / "marketplace.json").is_file():
        return bundled
    return None


def _plugin_runtime_root() -> Path:
    """Return the operator-writable copy used by the Codex plugin manager."""
    return hook_install.codex_config_path().parent / "custodian-codex-guard-plugin"


def _materialize_plugin_runtime(source: Path) -> Path:
    """Copy the packaged marketplace into Codex's user configuration area.

    Package directories may be root-owned or otherwise read-only.  Setup must
    never rewrite installed wheel contents merely to pin the live interpreter.
    """
    destination = _plugin_runtime_root()
    destination.mkdir(parents=True, exist_ok=True)
    for name in (".agents", "plugins"):
        source_dir = source / name
        if not source_dir.is_dir():
            raise FileNotFoundError(f"plugin bundle is incomplete: {source_dir}")
        shutil.copytree(source_dir, destination / name, dirs_exist_ok=True)
    return destination


def _mcp_command() -> list[str]:
    """Return the canonical command for launching the MCP guard server.

    Uses ``sys.executable -m custodian.codex_guard.mcp_server`` so the
    registration always points at the running interpreter rather than a
    possibly-stale bare shell script.
    """
    return [sys.executable, "-m", "custodian.codex_guard.mcp_server"]


def _verify_mcp_handshake(command: list[str]) -> bool:
    """Verify the MCP server responds to a JSON-RPC ``initialize`` call."""
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "custodian-test", "version": "0.0.0"},
        },
    })
    try:
        proc = subprocess.run(
            command,
            input=request + "\n",
            text=True,
            capture_output=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return False
        for line in proc.stdout.strip().splitlines():
            if not line.strip():
                continue
            resp = json.loads(line)
            if resp.get("result") and resp.get("id") == 1:
                return True
        return False
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return False


def _ensure_mcp_json(mcp_json_path: Path) -> bool:
    """Idempotently write/repair the MCP server registration.

    Always uses the absolute ``sys.executable -m custodian.codex_guard.mcp_server``
    form so stale bare-command registrations are replaced on every run.
    Verifies with a real JSON-RPC ``initialize`` handshake.
    """
    command = _mcp_command()

    payload: dict = {}

    if mcp_json_path.exists():
        try:
            existing = json.loads(mcp_json_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = existing
            if (
                existing.get("mcpServers", {}).get("custodian-codex-guard", {}).get("command")
                != command[0]
                or existing.get("mcpServers", {}).get("custodian-codex-guard", {}).get("args")
                != command[1:]
            ):
                print(f"replacing stale MCP registration at {mcp_json_path}")
        except (json.JSONDecodeError, OSError):
            pass  # corrupt file → overwrite

    servers = payload.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        payload["mcpServers"] = servers
    servers["custodian-codex-guard"] = {
        "command": command[0],
        "args": command[1:],
    }

    mcp_json_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_json_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    # Verify with an actual JSON-RPC handshake
    if _verify_mcp_handshake(command):
        print(f"MCP server at {mcp_json_path} verified via JSON-RPC initialize handshake")
        return True
    else:
        print(
            f"MCP server handshake failed — command: {' '.join(command)}",
            file=sys.stderr,
        )
        return False


def cmd_setup(args: argparse.Namespace) -> int:
    source_root = _repo_root()
    if source_root is None:
        print(
            "plugin marketplace is missing from the installed package; "
            "reinstall custodian-codex-guard",
            file=sys.stderr,
        )
        return 1

    root = source_root
    commands = [
        ["codex", "plugin", "marketplace", "add", str(root)],
        ["codex", "plugin", "add", PLUGIN_ID],
        ["codex", "mcp", "add", "custodian-codex-guard", "--", *_mcp_command()],
    ]
    if args.dry_run:
        print("would run: " + " ".join(_mcp_command()))
        for command in commands:
            print("would run: " + " ".join(command))
        print(f"would install PreToolUse enforcement hook into: {hook_install.codex_config_path()}")
        print(f"  command: {hook_install.hook_command()}")
        return 0

    try:
        root = _materialize_plugin_runtime(source_root)
    except OSError as exc:
        print(
            f"plugin staging failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    commands = [
        ["codex", "plugin", "marketplace", "add", str(root)],
        ["codex", "plugin", "add", PLUGIN_ID],
        ["codex", "mcp", "add", "custodian-codex-guard", "--", *_mcp_command()],
    ]
    plugin_mcp = root / "plugins" / "custodian-codex-guard" / ".mcp.json"
    if not _ensure_mcp_json(plugin_mcp):
        print("MCP server registration failed — guard is not reachable", file=sys.stderr)
        return 1
    if not _command_available("codex"):
        print("Codex CLI is not installed or not on PATH", file=sys.stderr)
        return 1
    # Remove a stale global registration before installing the exact absolute
    # interpreter command. A missing registration is expected on first setup.
    subprocess.run(
        ["codex", "mcp", "remove", "custodian-codex-guard"],
        text=True, capture_output=True, timeout=30,
    )
    for command in commands:
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"setup failed: {type(exc).__name__}", file=sys.stderr)
            return 1
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            print(f"setup failed: {detail}", file=sys.stderr)
            return 1
    print(f"installed and enabled: {PLUGIN_ID}")
    # The hook -- not the plugin/MCP tool -- is what makes the guard mandatory:
    # Codex enforces it on every tool call before its own approval decision, so
    # it holds even under approval_policy=never or a trusted project -- but only
    # once the hook is TRUSTED or MANAGED. A plain user-level install (the
    # default here, no --managed-lock) starts Untrusted and is silently SKIPPED
    # in non-interactive `codex exec` until approved once in the TUI (see
    # docs/ROADMAP-codex-kernel-enforcement.md's live smoke-test finding). The
    # print statements below already say this; don't let this comment drift
    # back to the unqualified claim. The MCP server above stays for
    # receipt/approval visibility either way.
    try:
        path = hook_install.install(matcher=args.matcher)
        print(f"installed PreToolUse enforcement hook: {path}")
    except hook_install.HookInstallError as exc:
        print(f"WARNING: could not install enforcement hook ({exc}); "
              "the guard is NOT mandatory until this is fixed", file=sys.stderr)
        return 1

    if getattr(args, "managed_lock", False):
        # Always-on, unstrippable enforcement: a managed hook is auto-trusted and
        # runs in non-interactive exec with no TUI trust prompt. Needs write
        # access to the managed dir (root-owned /etc/codex by default).
        try:
            cfg, req = hook_install.install_managed(matcher=args.matcher)
            print(f"installed MANAGED (always-on) hook: {cfg}")
            if req:
                print(f"locked config to managed hooks only: {req}")
        except (PermissionError, OSError) as exc:
            print(f"WARNING: managed install needs write access to "
                  f"{hook_install.managed_dir()} ({type(exc).__name__}); "
                  f"{hook_install.elevation_hint()}, or set CUSTODIAN_CODEX_MANAGED_DIR",
                  file=sys.stderr)
            return 1
    else:
        # A user-level hook starts UNTRUSTED and is skipped in exec until trusted.
        print("IMPORTANT: run `codex` once interactively and approve the hook "
              "trust prompt, or the hook is skipped in non-interactive runs.")
        print("For always-on, unstrippable enforcement instead: "
              "sudo custodian-codex setup --managed-lock")

    # Phase 2 -- surface the Paladin credential path so the operator knows how
    # Codex resolves secrets it doesn't hold. This never blocks setup: Paladin
    # is optional and every branch is advisory.
    if paladin_bridge.vault_configured():
        helpers = paladin_bridge.git_helpers()
        if helpers:
            wired = ", ".join(f"{host} -> paladin://{ref}" for host, ref in helpers)
            print(f"Paladin: vault configured; git credentials wired for {wired}")
        else:
            print("Paladin: vault configured but no git host is wired yet. "
                  "Wire one so Codex git ops resolve tokens from the vault:")
            print("  custodian-codex paladin-git <host> <ref>   "
                  "(e.g. github.com github_token)")
    elif paladin_bridge.paladin_available():
        print("Paladin: installed but no vault yet. `paladin init` then "
              "`custodian-codex paladin-git <host> <ref>` to keep secrets out "
              "of Codex's context.")
    print("start a new Codex thread to load the guard")
    return 0


def cmd_paladin_git(args: argparse.Namespace) -> int:
    """Wire git -> Paladin for one host/ref so Codex git ops pull tokens from
    the encrypted vault at request time -- never from config, a URL, or argv.

    This is the transparent half of "Codex checks Paladin first for a password
    it doesn't hold": once wired, `git push`/`git fetch` to <host> just work,
    with the token resolved from the vault and never entering Codex's context.
    """
    if not paladin_bridge.paladin_available():
        print("the `paladin` CLI is not on PATH; install Paladin first",
              file=sys.stderr)
        return 1
    if not paladin_bridge.vault_configured():
        print(f"no Paladin vault at {paladin_bridge.vault_path()}; run "
              "`paladin init` and `paladin add <ref>` first", file=sys.stderr)
        return 1
    ok, message = paladin_bridge.wire_git_helper(args.host, args.ref)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


def cmd_disable(_: argparse.Namespace) -> int:
    """Operator escape hatch: remove the plugin without deleting evidence."""
    if not _command_available("codex"):
        print("Codex CLI is not installed or not on PATH", file=sys.stderr)
        return 1
    try:
        result = subprocess.run(
            ["codex", "plugin", "remove", PLUGIN_ID],
            text=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"disable failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    if result.returncode:
        print(f"disable failed: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
        return 1
    print("Codex Guard disabled; receipts and approval evidence were preserved.")
    print("start a new Codex thread to apply the change")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    operator = args.operator or os.environ.get("USER") or os.environ.get("USERNAME")
    if not operator:
        print("operator identity is required (--operator NAME)", file=sys.stderr)
        return 2
    store = ApprovalStore(_state_dir())
    approval_id = args.approval_id
    if approval_id == "latest":
        pending = []
        paths = store.approvals_dir.glob("*.json") if store.approvals_dir.exists() else ()
        for path in paths:
            try:
                candidate = store.get(path.stem)
            except (OSError, ApprovalError):
                continue
            if candidate.status == "pending" and candidate.expires_at >= time.time():
                pending.append(candidate)
        if not pending:
            print("approval denied: no unexpired pending approvals", file=sys.stderr)
            return 1
        approval_id = max(pending, key=lambda item: item.created_at).approval_id
    try:
        pending_record = store.get(approval_id)
        remaining = max(0, int(pending_record.expires_at - time.time()))
        digest = args.digest or pending_record.action_digest
        print(f"Approval: {approval_id}")
        print(f"Requester: {pending_record.requester}")
        print(f"Action digest: {pending_record.action_digest}")
        print(f"Expires in: {remaining // 60}m {remaining % 60:02d}s")
        if not sys.stdin.isatty():
            print(
                "approval denied: run this command in an interactive operator terminal",
                file=sys.stderr,
            )
            return 1
        answer = input("Approve this exact action once? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("approval cancelled")
            return 1
        record = store.approve(
            approval_id,
            approved_by=operator,
            expected_digest=digest,
        )
    except ApprovalError as exc:
        print(f"approval denied: {exc}", file=sys.stderr)
        return 1
    print(f"approved once: {record.approval_id} (expires {record.expires_at:.0f})")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    state = _state_dir()
    store = ApprovalStore(state)
    approval_dir = store.approvals_dir
    counts: dict[str, int] = {}
    for path in approval_dir.glob("*.json") if approval_dir.exists() else ():
        try:
            status = store.get(path.stem).status
        except (OSError, ApprovalError):
            status = "invalid"
        counts[status] = counts.get(status, 0) + 1
    print(f"state: {state}")
    print("approvals: " + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"))
    try:
        print(f"receipts: valid ({ReceiptChain(state).verify()})")
        return 0
    except Exception as exc:
        print(f"receipts: INVALID ({exc})")
        return 1


def _diagnose_stale_registration(mcp_json_path: Path) -> tuple[bool, str]:
    """Compare the registered MCP command/args against the live interpreter.

    Returns (is_stale, detail_string).  Stale means the command or args
    diverge from what ``sys.executable -m`` would produce, which happens
    when the Python interpreter was upgraded or the installation moved.
    """
    if not mcp_json_path.exists():
        return False, "no mcp.json found at " + str(mcp_json_path)

    try:
        registered = json.loads(mcp_json_path.read_text(encoding="utf-8"))
        cmd_entry = (
            registered.get("mcpServers", {})
            .get("custodian-codex-guard", {})
            .get("command", "")
        )
        args_entry = registered.get("mcpServers", {}).get(
            "custodian-codex-guard", {}
        ).get("args", [])
    except (json.JSONDecodeError, OSError):
        return False, "mcp.json parse error"

    current_cmd = sys.executable
    current_args = ["-m", "custodian.codex_guard.mcp_server"]

    detail = f"registered: {cmd_entry} {' '.join(args_entry)}  live: {current_cmd} {' '.join(current_args)}"

    if cmd_entry != current_cmd or args_entry != current_args:
        return True, detail

    return False, detail


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose the Custodian Codex Guard installation and the registered interpreter."""
    results: list[tuple[str, bool, str]] = []

    # Python version
    ok = sys.version_info >= (3, 11)
    results.append(("python", ok, f"{sys.version.split()[0]}"))

    # Codex CLI
    has_codex = _command_available("codex")
    results.append(("codex CLI", has_codex, shutil.which("codex") or "not on PATH"))

    # MCP command (canonical form)
    mcp_cmd = _mcp_command()
    mcp_available = _verify_mcp_handshake(mcp_cmd)
    results.append(
        ("MCP server", mcp_available, " ".join(mcp_cmd)),
    )

    # cwd mcp.json interpreter freshness
    mcp_json_path = Path.cwd() / "mcp.json"
    if mcp_json_path.exists():
        try:
            registered = json.loads(mcp_json_path.read_text(encoding="utf-8"))
            cmd_entry = (
                registered.get("mcpServers", {})
                .get("custodian-codex-guard", {})
                .get("command", "")
            )
            args_entry = registered.get("mcpServers", {}).get(
                "custodian-codex-guard", {}
            ).get("args", [])
            detail = f"{cmd_entry} {' '.join(args_entry)}"
            results.append(
                ("registered interpreter", bool(cmd_entry), detail),
            )

            # Diagnose stale registration: compare against current interpreter.
            is_stale, stale_detail = _diagnose_stale_registration(mcp_json_path)
            tag = "stale" if is_stale else "in sync"
            results.append(("cwd freshness", True, f"{tag}: {stale_detail}"))

            # Validate actual JSON-RPC initialize against the *registered* command.
            if cmd_entry:
                reg_cmd = [cmd_entry] + args_entry
                reg_handshake = _verify_mcp_handshake(reg_cmd)
                results.append(
                    ("cwd handshake", reg_handshake, "registered command OK" if reg_handshake else "registered command FAIL"),
                )

        except (json.JSONDecodeError, OSError):
            results.append(("mcp.json", False, "parse error"))

    # Plugin .mcp.json interpreter freshness
    configured_root = _plugin_runtime_root()
    root = configured_root if (
        configured_root / ".agents/plugins/marketplace.json"
    ).is_file() else _repo_root()
    if root is not None:
        plugin_mcp = root / "plugins" / "custodian-codex-guard" / ".mcp.json"
        if plugin_mcp.exists():
            is_stale, stale_detail = _diagnose_stale_registration(plugin_mcp)
            tag = "stale" if is_stale else "in sync"
            results.append(
                ("plugin .mcp.json", not is_stale, f"{tag}: {stale_detail}"),
            )
            if not is_stale:
                try:
                    reg = json.loads(plugin_mcp.read_text(encoding="utf-8"))
                    cmd_entry = reg.get("mcpServers", {}).get("custodian-codex-guard", {}).get("command", "")
                    args_entry = reg.get("mcpServers", {}).get("custodian-codex-guard", {}).get("args", [])
                    if cmd_entry:
                        reg_handshake = _verify_mcp_handshake([cmd_entry] + args_entry)
                        results.append(
                            ("plugin handshake", reg_handshake, "OK" if reg_handshake else "FAIL"),
                        )
                except (json.JSONDecodeError, OSError):
                    results.append(("plugin .mcp.json", False, "parse error"))

    # PreToolUse enforcement hook -- the mandatory-enforcement check. Without
    # it the guard is only advisory (the model must choose to call the MCP tool).
    managed = hook_install.managed_status()
    hook_state = hook_install.status()
    if managed["installed"]:
        # Managed hooks are always-on and auto-trusted -- the strongest state.
        lock = "locked to managed-only" if managed["locked"] else "not locked"
        results.append(("enforcement hook", True, f"MANAGED always-on ({lock}): {managed['path']}"))
    elif not hook_state["installed"]:
        results.append(("enforcement hook", False,
                        f"NOT installed in {hook_state['path']} -- guard is advisory only; run setup"))
    elif not hook_state["interpreter_current"]:
        results.append(("enforcement hook", False,
                        f"stale interpreter ({hook_state['command']}); rerun setup"))
    else:
        # Installed user-level. Codex silently SKIPS an untrusted hook in
        # non-interactive `exec`, and its trust state is a content hash in
        # Codex's state db that we cannot read here -- so we can NOT confirm
        # this hook actually enforces. Report WARN, never OK: a soft "OK" here
        # would let an operator (or a judge) believe they are protected when
        # enforcement may be silently inert. Only MANAGED is verifiably on.
        results.append(("enforcement hook", "warn",
                        f"{hook_state['path']} -- INSTALLED BUT NOT VERIFIABLE. "
                        "Codex skips untrusted hooks in `codex exec`; approve the "
                        "one-time TUI trust prompt, or use --managed-lock for "
                        "verifiable always-on enforcement."))

    # Approval store
    state = _state_dir()
    try:
        store = ApprovalStore(state)
        _ = store.list_records()
        results.append(("approval store", True, str(store.approvals_dir)))
    except Exception as exc:
        results.append(("approval store", False, str(exc)))

    # Receipt chain
    try:
        chain = ReceiptChain(state)
        chain.verify()
        results.append(("receipt chain", True, "verified"))
    except Exception as exc:
        results.append(("receipt chain", False, str(exc)))

    # Paladin credential path (Phase 2). Optional dependency: its absence is a
    # WARN, never a FAIL -- codex-guard is fully functional without it, but a
    # configured Paladin is how Codex resolves a secret it doesn't hold without
    # prompting for or inlining a raw value. All checks are value-free (no unlock).
    pal = paladin_bridge.status_summary()
    if not pal["available"]:
        results.append(("paladin", "warn",
                        "not installed -- credential actions escalate to a human; "
                        "install custodian-paladin to resolve secrets from a vault"))
    elif not pal["vault_configured"]:
        results.append(("paladin", "warn",
                        f"installed but no vault at {pal['vault_path']} -- run "
                        "`paladin init`, then `custodian-codex paladin-git <host> <ref>`"))
    elif not pal["git_helpers"]:
        results.append(("paladin", "warn",
                        "vault configured but no git host wired -- run "
                        "`custodian-codex paladin-git <host> <ref>` so Codex git "
                        "ops resolve tokens from the vault"))
    else:
        wired = ", ".join(f"{host}->paladin://{ref}" for host, ref in pal["git_helpers"])
        results.append(("paladin", True, f"vault configured; git wired for {wired}"))

    # Three states: True -> OK, "warn" -> WARN (installed but unverifiable),
    # False -> FAIL. WARN must never read as OK (see the enforcement-hook check).
    for name, passed, detail in results:
        tag = "WARN" if passed == "warn" else ("OK" if passed else "FAIL")
        print(f"  {tag}  {name:<20} {detail}")

    has_fail = any(p is False for _, p, _ in results)
    enforcement_warn = any(
        name == "enforcement hook" and p == "warn" for name, p, _ in results
    )
    paladin_warn = any(name == "paladin" and p == "warn" for name, p, _ in results)
    has_warn = any(p == "warn" for _, p, _ in results)
    if has_fail:
        print("\nSome checks failed — see above.", file=sys.stderr)
    elif enforcement_warn:
        # Not a clean pass: do NOT tell the operator they are protected.
        print("\n⚠ Enforcement is installed but NOT verifiably active. Codex "
              "silently skips an untrusted hook in `codex exec`. Confirm the "
              "one-time Codex trust prompt was approved, or run "
              "`custodian-codex setup --managed-lock` for verifiable, always-on "
              "enforcement. Do not assume you are protected until then.",
              file=sys.stderr)
    elif paladin_warn:
        # Enforcement is fine; only the credential path is not fully wired.
        # Guard still works -- credential actions just escalate to a human
        # instead of resolving from a vault.
        print("\n⚠ Enforcement is active, but the Paladin credential path is not "
              "fully wired (see above). Codex will escalate credential actions to "
              "a human rather than resolving them from a vault. Wire it with "
              "`custodian-codex paladin-git <host> <ref>` for hands-off, "
              "leak-proof secret delivery.", file=sys.stderr)
    else:
        print("\nAll checks passed. Consequential actions fail closed unless approved.")
    # WARN keeps exit 0 (the install is not broken), but the banner above makes
    # the unverified state unmissable. A FAIL (missing/stale hook) exits 1.
    return 1 if has_fail else 0


def cmd_deny(args: argparse.Namespace) -> int:
    """Headless denial: reject a pending approval by ID (no TTY required)."""
    store = ApprovalStore(_state_dir())
    operator = args.operator or os.environ.get("USER") or os.environ.get("USERNAME")
    if not operator:
        print("operator identity is required (--operator NAME)", file=sys.stderr)
        return 2

    approval_id = args.approval_id
    if approval_id == "latest":
        pending = []
        paths = store.approvals_dir.glob("*.json") if store.approvals_dir.exists() else ()
        for path in paths:
            try:
                candidate = store.get(path.stem)
            except (OSError, ApprovalError):
                continue
            if candidate.status == "pending" and candidate.expires_at >= time.time():
                pending.append(candidate)
        if not pending:
            print("deny denied: no unexpired pending approvals", file=sys.stderr)
            return 1
        approval_id = max(pending, key=lambda item: item.created_at).approval_id

    try:
        record = store.get(approval_id)
        if record.status != "pending":
            print(f"deny skipped: approval {approval_id} is {record.status}", file=sys.stderr)
            return 1
        denied = store.deny(approval_id, denied_by=operator)
        print(f"denied: {denied.approval_id} (by {denied.approved_by})")
        return 0
    except ApprovalError as exc:
        print(f"deny failed: {exc}", file=sys.stderr)
        return 1


def cmd_hook_uninstall(args: argparse.Namespace) -> int:
    """Operator escape hatch: turn the guard off if it is misbehaving.

    Without --managed, removes the user-level hook. With --managed, removes the
    always-on managed hook and the managed-only lock (needs root/admin write to
    the managed dir) so Codex runs normally again.
    """
    if getattr(args, "managed", False):
        try:
            removed = hook_install.uninstall_managed()
        except hook_install.HookInstallError as exc:
            print(f"hook-uninstall --managed failed: {exc}", file=sys.stderr)
            return 1
        except (PermissionError, OSError) as exc:
            print(f"hook-uninstall --managed needs write access to "
                  f"{hook_install.managed_dir()} ({type(exc).__name__}); "
                  f"{hook_install.elevation_hint()}", file=sys.stderr)
            return 1
        print(f"removed managed enforcement hook + lock from {hook_install.managed_dir()}"
              if removed else f"no managed Custodian hook present in {hook_install.managed_dir()}")
        return 0
    try:
        removed = hook_install.uninstall()
    except hook_install.HookInstallError as exc:
        print(f"hook-uninstall failed: {exc}", file=sys.stderr)
        return 1
    path = hook_install.codex_config_path()
    print(f"removed enforcement hook from {path}" if removed
          else f"no Custodian enforcement hook present in {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="custodian-codex")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="install the plugin, MCP server, and enforcement hook")
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument("--matcher", default=hook_install.DEFAULT_MATCHER,
                       help="tool-name regex the hook governs (default '.*' = all tools)")
    setup.add_argument("--managed-lock", action="store_true",
                       help="also install an always-on managed hook and lock config "
                            "to managed hooks only (needs root/managed-dir write)")
    setup.set_defaults(fn=cmd_setup)
    hook_uninstall = sub.add_parser("hook-uninstall",
                                    help="operator escape hatch: remove the enforcement hook")
    hook_uninstall.add_argument("--managed", action="store_true",
                                help="remove the always-on MANAGED hook + lock "
                                     "(needs root/admin write to the managed dir)")
    hook_uninstall.set_defaults(fn=cmd_hook_uninstall)
    disable = sub.add_parser("disable", help="operator escape hatch; preserve evidence")
    disable.set_defaults(fn=cmd_disable)
    paladin_git = sub.add_parser(
        "paladin-git",
        help="wire git -> Paladin for one host so Codex resolves tokens from the vault")
    paladin_git.add_argument("host", help="git host, e.g. github.com")
    paladin_git.add_argument("ref", help="vault ref name to resolve for that host")
    paladin_git.set_defaults(fn=cmd_paladin_git)
    approve = sub.add_parser("approve", help="approve one exact pending action")
    approve.add_argument("approval_id", help="approval UUID, or 'latest'")
    approve.add_argument(
        "--digest",
        help="optional full digest copied from Guard for independent verification",
    )
    approve.add_argument("--operator")
    approve.set_defaults(fn=cmd_approve)
    deny = sub.add_parser("deny", help="headless denial of a pending approval")
    deny.add_argument("approval_id", help="approval UUID, or 'latest'")
    deny.add_argument("--operator", help="operator identity (falls back to $USER)")
    deny.set_defaults(fn=cmd_deny)
    status = sub.add_parser("status", help="verify receipts and show approval counts")
    status.set_defaults(fn=cmd_status)
    doctor = sub.add_parser("doctor", help="check the local Codex Guard installation")
    doctor.set_defaults(fn=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
