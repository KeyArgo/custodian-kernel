#!/usr/bin/env python3
"""Deterministic, no-network demo for Custodian Guard for Codex."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from custodian.codex_guard import evaluate_action
from custodian.codex_guard.approvals import ApprovalError, ApprovalStore, action_digest
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

        # Bind human approval to one exact consequential action. The store
        # persists only the digest and bounded metadata, never the command.
        approvals = ApprovalStore(root / "state")
        action = {
            "tool": "shell-exec",
            "action_kind": "production",
            "arguments": {"command": "deploy --environment staging"},
            "workspace": str(workspace),
            "requester": "codex:judge-demo",
        }
        digest = action_digest(**action)
        pending = approvals.request(
            digest=digest, requester=action["requester"], ttl_seconds=60,
        )
        approvals.approve(pending.approval_id, approved_by="human-operator")
        mutated = dict(action)
        mutated["arguments"] = {"command": "deploy --environment production"}
        try:
            approvals.consume(
                pending.approval_id,
                digest=action_digest(**mutated),
                requester=action["requester"],
            )
        except ApprovalError:
            print("Argument mutation: BLOCKED (action digest changed)")
        else:
            print("Argument mutation: FAILED")
            return 1
        approvals.consume(
            pending.approval_id, digest=digest, requester=action["requester"],
        )
        print("Exact approval: CONSUMED ONCE (action digest bound)")
        try:
            approvals.consume(
                pending.approval_id, digest=digest, requester=action["requester"],
            )
        except ApprovalError:
            print("Approval replay: BLOCKED (single-use claim already consumed)")
        else:
            print("Approval replay: FAILED")
            return 1

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
