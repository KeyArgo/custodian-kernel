"""Refund-pack agent: customer email -> Envelope, via the real Nemotron model.

The prompt deliberately gives the model the email, the policy, and the *names*
of the ledger fields it may assert against -- never their values. That is what
makes the downstream verifier meaningful: the model is guessing what the truth
should be, and an independent deterministic check decides whether it guessed
right.
"""
from __future__ import annotations

from pathlib import Path

from custodian.packs.agent import LLMClient, parse_envelope
from custodian.packs.base import Envelope

_HERE = Path(__file__).parent
_POLICY_REF = (
    _HERE.parent.parent.parent / "skills" / "payments" / "stripe-spend"
    / "references" / "refund-policy.md"
)

# The assertable ground-truth fields, by name and meaning only. NO VALUES.
# `id` of a claim that cites an exception MUST be one of the valid exception
# codes so the deterministic adapter can recognise it.
FIELD_SCHEMA = {
    "order.purchase_age_days": "integer days since the order was placed",
    "order.delivered": "boolean: did the carrier mark this order delivered",
    "order.customer_acknowledged_at": "timestamp the customer confirmed receipt, or null",
    "order.defect_report_on_file": "boolean: is there a defect report on file for this order",
    "customer.prior_refunds_90d": "integer count of this customer's refunds in the last 90 days",
    "customer.tenure_months": "integer months this customer has had an account",
}

RELATIONS = "eq | neq | gt | lt | gte | lte | exists | absent"

SYSTEM_PROMPT = """You are a refund-triage analyst for an e-commerce business. You read a
customer's message and produce a STRUCTURED JUDGMENT ENVELOPE as JSON. You do NOT decide
whether money moves -- a separate deterministic system verifies your claims against the real
order database and a human signs off. Your job is to read the mess accurately and lay out the
facts to check.

Hard rules:
- You CANNOT see the real order data. You only know the field NAMES below. For each factual
  thing the customer asserts that bears on the refund, emit a claim naming the field, the
  relation, and the value you EXPECT the real data to have if the customer is telling the truth.
  A later step looks up the real value and decides if your claim holds. Do not pretend to know
  the real value.
- Always quote the customer LITERALLY in `customer_quote` -- the exact words, not a paraphrase.
- `recommended_disposition` is ADVISORY ONLY. Be honest: if you are genuinely unsure, set it to
  "escalate_ambiguous" and a low confidence. A confident wrong guess is worse than "I'm not sure".
- If the customer cites a reason that maps to an exception, the claim `id` MUST be exactly one of:
  defect, non_delivery, billing_error. Otherwise use any short snake_case id.

Output ONLY a single JSON object, no prose, with this shape:
{
  "recommended_disposition": "approve_recommended | deny_recommended | flag_abuse | escalate_ambiguous",
  "confidence": 0.0-1.0,
  "agent_summary": "one or two plain sentences a human reviewer can skim",
  "policy_clauses_cited": [{"source":"policy","quote":"<verbatim policy line you relied on>","locator":"refund-policy.md:<section>"}],
  "claims": [{"id":"<code or snake_case>","statement":"<what it asserts>","customer_quote":"<literal>","ledger_path":"<one of the fields>","relation":"<relation>","asserted":<expected value>}]
}"""


def _policy_text() -> str:
    try:
        return _POLICY_REF.read_text()
    except OSError:
        return "(refund policy reference unavailable; rely on standard 30-day window with defect/non_delivery/billing_error exceptions)"


def build_user_prompt(case_input: dict) -> str:
    fields = "\n".join(f"  - {p}: {desc}" for p, desc in FIELD_SCHEMA.items())
    return (
        f"REFUND POLICY (the rules you must reason within):\n{_policy_text()}\n\n"
        f"GROUND-TRUTH FIELDS YOU MAY ASSERT AGAINST (names and meaning only -- "
        f"you do NOT get their values):\n{fields}\n\n"
        f"ALLOWED RELATIONS: {RELATIONS}\n\n"
        f"REQUEST METADATA (facts, not judgment): customer_id={case_input['customer_id']}, "
        f"order_id={case_input['order_id']}, amount={case_input['amount']}, "
        f"requested_action=refund.create\n\n"
        f"CUSTOMER MESSAGE:\n\"\"\"\n{case_input['customer_email']}\n\"\"\"\n\n"
        f"Produce the JSON envelope now."
    )


def extract_envelope(case_input: dict, client: LLMClient) -> Envelope:
    """Run the agent to produce an Envelope for one case. `case_input` carries
    the request metadata + the raw customer_email."""
    raw = client.complete(SYSTEM_PROMPT, build_user_prompt(case_input))
    fallback_meta = {
        "case_id": case_input.get("case_id", case_input["order_id"]),
        "customer_id": case_input["customer_id"],
        "order_id": case_input["order_id"],
        "amount": case_input["amount"],
        "requested_action": "refund.create",
    }
    return parse_envelope(raw, fallback_meta=fallback_meta)
