"""Machine-readable installed health confirmation.

Reports distribution names/versions, component availability, artifact
integrity, and appends a value-free tamper-evident confirmation to
the Custodian ledger.
"""
from __future__ import annotations

import importlib.metadata
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

from custodian.universal_ledger import LedgerEvent, UniversalLedger


def _distribution_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _is_source_install(dist_name: str) -> bool:
    try:
        dist = importlib.metadata.distribution(dist_name)
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            info = json.loads(direct_url)
            if info.get("url", "").startswith("file://"):
                return True
        for line in (dist.read_text("RECORD") or "").splitlines():
            if "../../" in line or ".." in line.split(",")[0]:
                return True
        return False
    except Exception:
        return False


def _data_locations(state_dir: Path) -> list[dict]:
    """Check data directories exist without exposing their contents."""
    checks = []
    for candidate in (
        Path.home() / ".custodian",
        Path.home() / ".paladin",
        Path.home() / ".talaria",
        state_dir,
    ):
        checks.append({
            "exists": candidate.exists(),
            "is_dir": candidate.is_dir() if candidate.exists() else False,
        })
    return checks


def _command_in_prefix(name: str) -> bool:
    """Check if command exists in the current interpreter's bin directory."""
    bin_dir = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    ext = ".exe" if os.name == "nt" else ""
    return (bin_dir / f"{name}{ext}").is_file() or (bin_dir / f"{name}{ext}").is_symlink()


def _installation_proof() -> dict | None:
    proof_file = Path(sys.prefix) / "installation-proof.json"
    if not proof_file.is_file():
        return None
    try:
        proof = json.loads(proof_file.read_text(encoding="utf-8"))
        relative = proof["record_relative"]
        record = (Path(sys.prefix) / relative).resolve()
        if not record.is_relative_to(Path(sys.prefix).resolve()) or not record.is_file():
            return {"valid": False, "reason": "installed RECORD missing"}
        actual = hashlib.sha256(record.read_bytes()).hexdigest()
        return {
            "valid": actual == proof.get("record_sha256"),
            "artifact_sha256": proof.get("artifact_sha256"),
            "record_sha256": actual,
        }
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"valid": False, "reason": "installation proof unreadable"}


def run(args) -> int:
    state_dir = Path(getattr(args, "state_dir", ".")).resolve()
    ledger_path = state_dir / "universal_ledger.db"

    health: dict = {
        "status": "pass",
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "distributions": {},
        "components": {},
        "commands": {},
        "installation_proof": None,
    }

    for dist in ("custodian-kernel", "custodian-codex-guard", "custodian-talaria"):
        ver = _distribution_version(dist)
        if ver is not None:
            src = _is_source_install(dist)
            health["distributions"][dist] = {"version": ver, "source_install": src}

    health["components"] = {
        "kernel": "custodian-kernel" in health["distributions"],
        "paladin": "custodian-kernel" in health["distributions"],
        "codex_guard": "custodian-codex-guard" in health["distributions"],
        "talaria": "custodian-talaria" in health["distributions"],
    }

    for cmd in (
        "custodian", "custodian-verify", "paladin", "paladin-import",
        "custodian-codex", "custodian-codex-guard-mcp", "talaria",
    ):
        health["commands"][cmd] = _command_in_prefix(cmd)

    health["data_locations"] = _data_locations(state_dir)
    health["installation_proof"] = _installation_proof()

    required = []
    if "custodian-kernel" in health["distributions"]:
        required += ["custodian", "custodian-verify", "paladin", "paladin-import"]
    if "custodian-codex-guard" in health["distributions"]:
        required += ["custodian-codex", "custodian-codex-guard-mcp"]
    if "custodian-talaria" in health["distributions"]:
        required += ["talaria"]
    if not health["distributions"] or any(not health["commands"][name] for name in required):
        health["status"] = "fail"
    if health["installation_proof"] and not health["installation_proof"].get("valid"):
        health["status"] = "fail"

    output_format = getattr(args, "format", "text")
    if output_format == "json":
        print(json.dumps(health, indent=2, sort_keys=True))
    else:
        print("Custodian Health Check")
        print("=====================")
        print(f"Status:    {health['status'].upper()}")
        print(f"Timestamp: {health['timestamp_iso']}")
        print()
        for dist, info in sorted(health["distributions"].items()):
            tag = "source" if info["source_install"] else "installed"
            print(f"  {dist}: {info['version']} ({tag})")
        for comp, avail in sorted(health["components"].items()):
            print(f"  {comp}: {'AVAILABLE' if avail else 'NOT INSTALLED'}")
        if health["installation_proof"]:
            proof = health["installation_proof"]
            print(f"  installation proof: {'VALID' if proof.get('valid') else 'INVALID'}")
            if proof.get("artifact_sha256"):
                print(f"  artifact hash: {proof['artifact_sha256'][:16]}...")

    if ledger_path.exists():
        try:
            ledger = UniversalLedger(ledger_path)
            event = LedgerEvent(
                correlation_id=f"health-{uuid.uuid4()}",
                requester="system",
                provider="custodian",
                action="health-check",
                lifecycle_event="executed",
                metadata={"status": health["status"], "ts": int(time.time())},
            )
            digest = ledger.append(event)
            if output_format != "json":
                print(f"\nHealth confirmation appended to ledger (digest: {digest[:16]}...)")
        except Exception as exc:
            if output_format != "json":
                print(f"\nWarning: could not append health event to ledger: {exc}")

    return 0 if health["status"] == "pass" else 1


def register(sub) -> None:
    p = sub.add_parser(
        "health",
        help="Machine-readable installed health confirmation",
        description="Check installed distributions, components, and append a "
                    "tamper-evident health event to the ledger. "
                    "No secrets are exposed.",
    )
    p.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    p.add_argument("--state-dir", default=str(Path.home() / ".custodian"),
                   help="Kernel state directory (default: ~/.custodian)")
    p.set_defaults(func=run)
