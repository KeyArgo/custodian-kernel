"""The purchasing (accounts payable) pack -- pack #2, proving the engine is
reusable.

Same shape as the refund pack: a domain policy + a ground-truth ledger + a
deterministic adapter, all sitting on the unchanged engine, verifier, and
kernel. What's DIFFERENT, and why it matters: refunds always escalate, but a
small, fully-clean invoice from an approved vendor that matches its purchase
order can pay AUTONOMOUSLY here -- the kernel band permits it. So pack #2
exercises a kernel outcome (AUTONOMOUS) the refund pack never reaches, on the
exact same machinery.

The lie-catch is identical and just as load-bearing: a vendor that invoices
more than its authorized PO produces a CONTRADICTED claim, and the adapter
refuses to pay no matter how clean the invoice text reads.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from custodian.packs.base import ClaimStatus, Envelope, PolicyPack

_HERE = Path(__file__).parent

# Disposition vocabulary for payables.
AUTO_PAY = "auto_pay"          # clean, in-band -> the kernel may execute with no human
ESCALATE = "escalate_approval"  # legitimate but needs a human signature
FLAG_HOLD = "flag_hold"         # something is wrong -> hold and investigate


class PurchasingPack(PolicyPack):
    name = "purchasing"
    requested_action = "invoice.pay"
    # Only a clean auto_pay is even eligible to execute without a human; the
    # kernel band still has to permit the amount on top of that.
    autonomous_dispositions = frozenset({AUTO_PAY})

    def __init__(self, rules: dict | None = None, ledger: dict | None = None):
        self.rules = rules or yaml.safe_load((_HERE / "purchasing_rules.yaml").read_text())
        self.ledger = ledger or json.loads((_HERE / "vendor_ledger.json").read_text())

    # -- ground truth -------------------------------------------------------
    def ledger_scope(self, envelope: Envelope) -> dict:
        """Flatten vendor + PO + derived invoice/budget facts into one dict so
        claims can address it with simple dotted paths like 'po.amount',
        'vendor.approved', or 'invoice.already_paid'."""
        vendor = self.ledger["vendors"].get(envelope.customer_id, {})
        po = vendor.get("pos", {}).get(envelope.order_id, {})
        already_paid = envelope.order_id in vendor.get("paid_pos", [])
        return {
            "vendor": {k: v for k, v in vendor.items() if k not in ("pos", "paid_pos")},
            "po": po,
            "invoice": {"already_paid": already_paid, "po_id": envelope.order_id},
            "budget": self.ledger.get("budget", {}),
        }

    # -- deterministic decision adapter -------------------------------------
    def adapter(self, envelope: Envelope) -> tuple[str, list[str], str]:
        scope = self.ledger_scope(envelope)
        vendor = scope["vendor"]
        po = scope["po"]
        invoice = scope["invoice"]
        budget = scope["budget"]
        reasons: list[str] = []

        contradicted = [c for c in envelope.claims if c.status == ClaimStatus.CONTRADICTED]

        # 1. LIE-CATCH (highest priority). A vendor invoice whose claims are
        #    refuted by the authorized PO cannot be paid, no matter how clean
        #    the invoice text reads -- the classic over-billing fraud a "summarize
        #    the invoice and pay it" pipeline would wire straight to money.
        if contradicted:
            for c in contradicted:
                reasons.append(
                    f"CONTRADICTED: vendor claim '{c.statement}' "
                    f"(invoice said: {c.customer_quote!r}) is refuted by the authorized record "
                    f"{c.ledger_path}={c.actual!r} (asserted {c.relation} {c.asserted!r})"
                )
            why = (
                "A script that pays what the invoice says would over-pay this vendor. Only a "
                "check against the authorized purchase order catches that the invoice doesn't "
                "match what was actually ordered."
            )
            return FLAG_HOLD, reasons, why

        # 2. Duplicate invoice: ground-truth payment history, not the invoice.
        if self.rules.get("block_duplicate_invoices", True) and invoice.get("already_paid"):
            reasons.append(
                f"duplicate: purchase order {invoice['po_id']!r} was already paid for this vendor"
            )
            why = (
                "A per-invoice script has no memory of what it already paid; it would pay the "
                "same invoice twice. Catching it needs the payment history."
            )
            return FLAG_HOLD, reasons, why

        # 3. Unapproved vendor -> a human must onboard/approve them first.
        if not vendor.get("approved", False):
            reasons.append(f"vendor {vendor.get('name', envelope.customer_id)!r} is not on the approved list")
            why = "Paying a brand-new, unvetted vendor is exactly the decision a human should make."
            return ESCALATE, reasons, why

        # 4. No matching open PO -> escalate (nothing authorized this spend).
        if self.rules.get("require_open_po", True) and po.get("status") != "open":
            reasons.append(f"no matching open purchase order (po status: {po.get('status', 'none')!r})")
            why = "An invoice with no authorizing purchase order has no basis to auto-pay."
            return ESCALATE, reasons, why

        amount = envelope.amount
        auto_max = self.rules["auto_pay_max"]
        remaining = budget.get("remaining")

        # 5. Over the autonomous threshold or over remaining budget -> human.
        if amount > auto_max:
            reasons.append(f"${amount:.2f} exceeds the autonomous-pay limit of ${auto_max:.2f}")
            why = "Large payments stay with a human even when everything else checks out."
            return ESCALATE, reasons, why
        if remaining is not None and amount > remaining:
            reasons.append(f"${amount:.2f} exceeds remaining {budget.get('category','')} budget ${remaining:.2f}")
            why = "Spending past the budget envelope is a human call, not an automatic one."
            return ESCALATE, reasons, why

        # 6. Clean, approved, matches PO, in budget, under the cap -> AUTO-PAY.
        #    This is the path refunds never have: the kernel will execute it.
        reasons.append(
            f"approved vendor, matches open PO {envelope.order_id}, ${amount:.2f} within "
            f"autonomous limit ${auto_max:.2f} and budget -- clean enough to pay automatically"
        )
        why = (
            "The boring, correct invoices should just get paid. The AI confirmed the invoice "
            "matches the order; the verifier confirmed nothing is contradicted; the kernel caps "
            "how much can ever move this way."
        )
        return AUTO_PAY, reasons, why
