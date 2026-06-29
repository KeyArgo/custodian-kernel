"""The refund triage pack.

What the AI does (in the Envelope): read a messy customer email, extract the
factual claims with the literal quote, cite the policy clauses it relied on,
and recommend a disposition. What this pack does (deterministically, here):
re-derive the disposition from ground truth so the AI's recommendation is
never trusted blindly, and -- the load-bearing part -- refuse to let a
positive recommendation stand on any claim the verifier marked CONTRADICTED.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from custodian.packs.base import Claim, ClaimStatus, Envelope, PolicyPack

_HERE = Path(__file__).parent

# Disposition vocabulary (advisory framing attached to the human escalation;
# the kernel still forces the human signature regardless).
APPROVE = "approve_recommended"
DENY = "deny_recommended"
FLAG_ABUSE = "flag_abuse"
ESCALATE_AMBIGUOUS = "escalate_ambiguous"


class RefundPack(PolicyPack):
    name = "refunds"
    requested_action = "refund.create"

    def __init__(self, rules: dict | None = None, ledger: dict | None = None):
        self.rules = rules or yaml.safe_load((_HERE / "refund_rules.yaml").read_text())
        self.ledger = ledger or json.loads((_HERE / "account_ledger.json").read_text())

    # -- ground truth -------------------------------------------------------
    def ledger_scope(self, envelope: Envelope) -> dict:
        """Flatten the customer + order ground truth into one dict so claims
        can address it with simple dotted paths like 'order.delivered' or
        'customer.prior_refunds_90d'."""
        cust = self.ledger["customers"].get(envelope.customer_id, {})
        order = cust.get("orders", {}).get(envelope.order_id, {})
        return {
            "customer": {k: v for k, v in cust.items() if k != "orders"},
            "order": order,
        }

    # -- deterministic decision adapter -------------------------------------
    def adapter(self, envelope: Envelope) -> tuple[str, list[str], str]:
        scope = self.ledger_scope(envelope)
        order = scope["order"]
        customer = scope["customer"]
        reasons: list[str] = []

        contradicted = [c for c in envelope.claims if c.status == ClaimStatus.CONTRADICTED]

        # 1. LIE-CATCH (highest priority). If the agent's case rests on a claim
        #    that ground truth refutes, the positive recommendation cannot
        #    stand -- no matter how fluent the agent was. This is exactly the
        #    failure mode a naive "summarize the email and approve" pipeline
        #    ships to a human as if it were true.
        if contradicted:
            for c in contradicted:
                reasons.append(
                    f"CONTRADICTED: customer claim '{c.statement}' "
                    f"(said: {c.customer_quote!r}) is refuted by ground truth "
                    f"{c.ledger_path}={c.actual!r} (asserted {c.relation} {c.asserted!r})"
                )
            why = (
                "A script that trusts the email text would approve this. The agent "
                "even recommended it. Only a check against independent ground truth "
                "catches that the customer's central claim is false."
            )
            return FLAG_ABUSE, reasons, why

        # 2. Serial abuse: ground-truth refund frequency, not the email.
        threshold = self.rules["serial_abuse_threshold"]
        prior = customer.get("prior_refunds_90d", 0)
        if prior >= threshold:
            reasons.append(
                f"serial-abuse signal: {prior} refunds in trailing "
                f"{self.rules['serial_abuse_window_days']}d >= threshold {threshold}"
            )
            why = (
                "A per-request script has no memory across requests; it cannot see "
                "that this is the Nth refund. Judgment requires the account history."
            )
            return FLAG_ABUSE, reasons, why

        # 3. Window + exceptions, computed from ground-truth purchase age.
        age = order.get("purchase_age_days")
        window = self.rules["window_days"]
        in_window = age is not None and age <= window

        cited_codes = {
            c.id for c in envelope.claims
            if c.id in self.rules["valid_exception_codes"]
            and c.status in (ClaimStatus.VERIFIED, ClaimStatus.UNVERIFIABLE)
        }

        if in_window:
            reasons.append(f"within {window}-day window (purchase age {age}d)")
            why = "In-window is the easy case a script also handles; nothing to prove here."
            return APPROVE, reasons, why

        # Out of window from here down.
        if cited_codes:
            reasons.append(
                f"out of window (age {age}d > {window}d) BUT a valid, "
                f"non-contradicted exception applies: {sorted(cited_codes)}"
            )
            why = (
                "A script sees age>window and denies. The agent read an exception out of "
                "prose ('it arrived broken') and tied it to a policy clause -- and the "
                "verifier confirmed the supporting facts aren't contradicted."
            )
            return APPROVE, reasons, why

        # 4. Genuine ambiguity: agent itself was unsure, nothing else fired.
        if (envelope.recommended_disposition == ESCALATE_AMBIGUOUS
                or envelope.confidence < self.rules["low_confidence_threshold"]):
            reasons.append(
                f"out of window, no valid exception, agent confidence "
                f"{envelope.confidence:.2f} -> genuine ambiguity, hand to human with the open question stated"
            )
            why = "The honest answer is 'I'm not sure' -- and saying so beats a confident wrong guess."
            return ESCALATE_AMBIGUOUS, reasons, why

        # 5. Out of window, no reason, no ambiguity -> deny recommendation.
        reasons.append(f"out of window (age {age}d > {window}d) with no valid exception claimed")
        why = "Clean deny; a script could also do this one. Not every case needs AI -- that's fine."
        return DENY, reasons, why
