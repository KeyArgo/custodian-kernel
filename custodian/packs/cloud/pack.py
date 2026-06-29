"""Cloud compute provisioning pack -- pack #3.

Proves the engine is rail-agnostic: the "money rail" here is a cloud provider
(Modal, Azure, NVIDIA NIM), not Stripe. Same engine, verifier, and kernel;
different domain policy and ledger. The kernel outcome this pack exercises that
refunds never reach: a small, fully-clean job on an approved instance type
can PROVISION AUTONOMOUSLY -- no human needed for routine compute.

The lie-catch is identical and just as load-bearing: an agent that under-reports
the real instance cost to slip under the autonomous cap produces a CONTRADICTED
claim on the price field, and the adapter refuses to provision regardless.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from custodian.packs.base import ClaimStatus, Envelope, PolicyPack

_HERE = Path(__file__).parent

# Disposition vocabulary for cloud provisioning.
AUTO_PROVISION = "auto_provision"    # clean, approved, in-cap -> kernel may execute autonomously
ESCALATE = "escalate_approval"       # legitimate but needs a human signature
FLAG_HOLD = "flag_hold"              # something is wrong -> hold and investigate


class CloudProvisioningPack(PolicyPack):
    name = "cloud"
    requested_action = "compute.provision"
    # Only auto_provision is eligible to execute without a human; kernel band
    # still has to permit the cost estimate on top of that.
    autonomous_dispositions = frozenset({AUTO_PROVISION})

    def __init__(self, rules: dict | None = None, ledger: dict | None = None):
        self.rules = rules or yaml.safe_load((_HERE / "cloud_rules.yaml").read_text())
        self.ledger = ledger or json.loads((_HERE / "resource_ledger.json").read_text())

    # -- ground truth -------------------------------------------------------
    def ledger_scope(self, envelope: Envelope) -> dict:
        """Flatten provider + instance catalog facts into one dict so claims
        can address dotted paths like 'instance.cost_per_hour', 'provider.approved',
        or 'job.already_running'."""
        provider = self.ledger["providers"].get(envelope.customer_id, {})
        instance = provider.get("instances", {}).get(envelope.order_id, {})
        already_running = envelope.order_id in provider.get("running_jobs", [])
        return {
            "provider": {k: v for k, v in provider.items() if k not in ("instances", "running_jobs")},
            "instance": instance,
            "job": {"already_running": already_running, "instance_id": envelope.order_id},
            "budget": self.ledger.get("budget", {}),
        }

    # -- deterministic decision adapter -------------------------------------
    def adapter(self, envelope: Envelope) -> tuple[str, list[str], str]:
        scope = self.ledger_scope(envelope)
        provider = scope["provider"]
        instance = scope["instance"]
        job = scope["job"]
        budget = scope["budget"]
        reasons: list[str] = []

        contradicted = [c for c in envelope.claims if c.status == ClaimStatus.CONTRADICTED]

        # 1. LIE-CATCH: agent under-reports the real cost to slip under the cap.
        if contradicted:
            for c in contradicted:
                reasons.append(
                    f"CONTRADICTED: agent claimed '{c.statement}' "
                    f"(said: {c.customer_quote!r}) but the price catalog shows "
                    f"{c.ledger_path}={c.actual!r} (asserted {c.relation} {c.asserted!r})"
                )
            why = (
                "A pipeline that trusts the agent's cost estimate would provision and get "
                "billed the real price. Only a check against the actual price catalog catches "
                "that the agent's figure doesn't match."
            )
            return FLAG_HOLD, reasons, why

        # 2. Duplicate job check.
        if self.rules.get("block_duplicate_jobs", True) and job.get("already_running"):
            reasons.append(f"duplicate: job {job['instance_id']!r} is already running for this provider")
            why = "Without a running-job registry, a re-triggered agent would spin up duplicate compute."
            return FLAG_HOLD, reasons, why

        # 3. Unapproved provider.
        if not provider.get("approved", False):
            reasons.append(f"provider {provider.get('name', envelope.customer_id)!r} is not on the approved list")
            why = "Provisioning from an unvetted cloud provider is a human decision."
            return ESCALATE, reasons, why

        # 4. Unapproved instance type.
        if self.rules.get("require_approved_instance", True) and not instance.get("approved", False):
            reasons.append(f"instance type {envelope.order_id!r} is not on the approved catalog")
            why = "Spinning up unapproved instance types bypasses the cost/compliance review."
            return ESCALATE, reasons, why

        amount = envelope.amount
        auto_max = self.rules["auto_provision_max"]
        remaining = budget.get("remaining")

        # 5. Over the autonomous threshold.
        if amount > auto_max:
            reasons.append(f"${amount:.2f}/hr exceeds the autonomous-provision limit of ${auto_max:.2f}/hr")
            why = "Expensive compute stays with a human even when everything else checks out."
            return ESCALATE, reasons, why

        if remaining is not None and amount > remaining:
            reasons.append(f"${amount:.2f} exceeds remaining {budget.get('category','')} budget ${remaining:.2f}")
            why = "Provisioning past the budget envelope is a human call."
            return ESCALATE, reasons, why

        # 6. Clean, approved, in-cap -> AUTO-PROVISION.
        reasons.append(
            f"approved provider + instance {envelope.order_id}, ${amount:.2f}/hr within "
            f"autonomous limit ${auto_max:.2f}/hr and budget -- clean enough to provision automatically"
        )
        why = (
            "Routine, small jobs from approved providers should just run. The AI confirmed the "
            "request; the verifier confirmed the cost is real; the kernel caps total exposure."
        )
        return AUTO_PROVISION, reasons, why
