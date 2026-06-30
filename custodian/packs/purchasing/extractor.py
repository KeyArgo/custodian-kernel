"""Purchasing-pack agent: vendor invoice text -> Envelope, via the real Nemotron model.

The prompt deliberately gives the model the vendor's invoice, the policy, and the *names*
of the ledger fields it may assert against -- never their values. That is what
makes the downstream verifier meaningful: the model is guessing what the truth
should be, and an independent deterministic check decides whether it guessed
right.
"""
from __future__ import annotations

from custodian.packs.agent import LLMClient, parse_envelope
from custodian.packs.base import Envelope

# The assertable ground-truth fields, by name and meaning only. NO VALUES.
FIELD_SCHEMA = {
    "po.amount": "numeric: the authorized dollar amount on the purchase order",
    "po.status": "string: open, closed, or cancelled -- the PO lifecycle state",
    "vendor.approved": "boolean: is this vendor on the approved vendor list",
    "vendor.name": "string: the vendor's registered company name",
    "invoice.already_paid": "boolean: has this purchase order already been paid",
    "budget.remaining": "numeric: remaining budget for this spend category",
}

RELATIONS = "eq | neq | gt | lt | gte | lte | exists | absent"

SYSTEM_PROMPT = """You are an accounts-payable analyst for a business. You read a
vendor's invoice message and produce a STRUCTURED JUDGMENT ENVELOPE as JSON. You do NOT decide
whether money moves -- a separate deterministic system verifies your claims against the real
purchase-order database and a human signs off. Your job is to read the invoice accurately and
lay out the facts to check.

Hard rules:
- You CANNOT see the real PO data. You only know the field NAMES below. For each factual
  thing the vendor asserts that bears on payment, emit a claim naming the field, the
  relation, and the value you EXPECT the real data to have if the vendor is telling the truth.
  A later step looks up the real value and decides if your claim holds. Do not pretend to know
  the real value.
- Always quote the vendor LITERALLY in `customer_quote` -- the exact words, not a paraphrase.
- `recommended_disposition` is ADVISORY ONLY. Be honest: if you are genuinely unsure, set it to
  "escalate_ambiguous" and a low confidence. A confident wrong guess is worse than "I'm not sure".
- If the invoice claims an amount, the claim `id` MUST be `amount_matches_po`.
- If the invoice asserts vendor approval, the claim `id` MUST be `vendor_approved`.
- If the invoice references a PO, the claim `id` MUST be `po_open`.

Output ONLY a single JSON object, no prose, with this shape:
{
  "recommended_disposition": "auto_pay | escalate_approval | flag_hold | escalate_ambiguous",
  "confidence": 0.0-1.0,
  "agent_summary": "one or two plain sentences a human reviewer can skim",
  "policy_clauses_cited": [{"source":"policy","quote":"<verbatim policy line you relied on>","locator":"purchasing_rules.yaml:<section>"}],
  "claims": [{"id":"<code or snake_case>","statement":"<what it asserts>","customer_quote":"<literal>","ledger_path":"<one of the fields>","relation":"<relation>","asserted":<expected value>}]
}"""


def build_user_prompt(case_input: dict) -> str:
    fields = "\n".join(f"  - {p}: {desc}" for p, desc in FIELD_SCHEMA.items())
    return (
        f"ACCOUNTS-PAYABLE POLICY (the rules you must reason within):\n"
        f"Pay invoices that match their purchase order, from approved vendors, within budget.\n"
        f"Block duplicate payments. Escalate new vendors and amounts over the autonomous limit.\n\n"
        f"GROUND-TRUTH FIELDS YOU MAY ASSERT AGAINST (names and meaning only -- "
        f"you do NOT get their values):\n{fields}\n\n"
        f"ALLOWED RELATIONS: {RELATIONS}\n\n"
        f"REQUEST METADATA (facts, not judgment): customer_id={case_input['customer_id']}, "
        f"order_id={case_input['order_id']}, amount={case_input['amount']}, "
        f"requested_action=invoice.pay\n\n"
        f"VENDOR INVOICE MESSAGE:\n\"\"\"\n{case_input['customer_email']}\n\"\"\"\n\n"
        f"Produce the JSON envelope now."
    )


def extract_envelope(case_input: dict, client: LLMClient) -> Envelope:
    """Run the agent to produce an Envelope for one case. `case_input` carries
    the request metadata + the raw vendor invoice text."""
    raw = client.complete(SYSTEM_PROMPT, build_user_prompt(case_input))
    fallback_meta = {
        "case_id": case_input.get("case_id", case_input["order_id"]),
        "customer_id": case_input["customer_id"],
        "order_id": case_input["order_id"],
        "amount": case_input["amount"],
        "requested_action": "invoice.pay",
    }
    return parse_envelope(raw, fallback_meta=fallback_meta)
