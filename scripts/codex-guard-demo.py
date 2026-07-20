#!/usr/bin/env python3
"""Deterministic, no-network demo for Custodian Guard for Codex."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from custodian.codex_guard import evaluate_action
from custodian.codex_guard.receipts import ReceiptChain


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="custodian-codex-demo-") as raw:
        root = Path(raw)
        workspace = root / "project"
        workspace.mkdir()
        chain = ReceiptChain(root / "state")
        cases = [
            ("Safe test", "shell-exec", "test", {"command": "python -m pytest"}),
            ("Workspace edit", "write_file", "write", {"path": str(workspace / "app.py"), "content": "pass"}),
            ("Secret read", "read_file", "read", {"path": str(workspace / ".env")}),
            ("Disguised delete", "shell-exec", "read", {"command": "rm -rf build/output"}),
            ("Production deploy", "shell-exec", "read", {"command": "kubectl apply -f deployment.yaml"}),
        ]
        print("Custodian Guard for Codex — capability-firewall demo\n")
        for label, tool, claimed, arguments in cases:
            decision = evaluate_action(
                tool=tool,
                action_kind=claimed,
                arguments=arguments,
                workspace=str(workspace),
                intent=label,
            ).to_dict()
            receipt = chain.append(decision, tool=tool, session_id="judge-demo")
            print(f"{label:19} claimed={claimed:5}  → {decision['verdict']:19} "
                  f"classified={decision['action_kind']:11} receipt={receipt['mac'][:12]}…")

        count = chain.verify()
        print(f"\nReceipt chain: VALID ({count} value-free, HMAC-linked decisions)")

        # Prove verification is meaningful without damaging the real chain.
        record = json.loads(chain.path.read_text().splitlines()[0])
        record["verdict"] = "denied" if record["verdict"] != "denied" else "autonomous"
        tampered = root / "tampered"
        tampered.mkdir()
        (tampered / chain.key_path.name).write_bytes(chain.key_path.read_bytes())
        (tampered / chain.path.name).write_text(json.dumps(record) + "\n")
        try:
            ReceiptChain(tampered).verify()
        except ValueError as exc:
            print(f"Tamper test: BLOCKED ({exc})")
            return 0
        print("Tamper test: FAILED")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
