"""Cloud-ops agent: compute provisioning request -> Envelope, via the real Nemotron model.

The prompt deliberately gives the model the provisioning request, the policy, and the *names*
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
    "instance.cost_per_hour": "numeric: catalog cost per hour for this instance type",
    "provider.approved": "boolean: is this provider on the approved list",
    "instance.approved": "boolean: is this instance type on the approved catalog",
    "job.already_running": "boolean: is this job already running for this provider",
    "budget.remaining": "numeric: remaining compute budget for this category",
}

RELATIONS = "eq | neq | gt | lt | gte | lte | exists | absent"

SYSTEM_PROMPT = """You are a cloud-ops analyst for a business. You read a
compute provisioning request and produce a STRUCTURED JUDGMENT ENVELOPE as JSON. You do NOT decide
whether resources spin up -- a separate deterministic system verifies your claims against the real
provider catalog and a human signs off. Your job is to read the request accurately and
lay out the facts to check.

Hard rules:
- You CANNOT see the real catalog data. You only know the field NAMES below. For each factual
  thing the request asserts that bears on provisioning, emit a claim naming the field, the
  relation, and the value you EXPECT the real data to have if the request is truthful.
  A later step looks up the real value and decides if your claim holds. Do not pretend to know
  the real value.
- Always quote the request LITERALLY in `customer_quote` -- the exact words, not a paraphrase.
- `recommended_disposition` is ADVISORY ONLY. Be honest: if you are genuinely unsure, set it to
  "escalate_ambiguous" and a low confidence. A confident wrong guess is worse than "I'm not sure".
- If the request claims a cost, the claim `id` MUST be `cost_accurate`.
- If the request asserts provider approval, the claim `id` MUST be `provider_approved`.
- If the request asserts instance approval, the claim `id` MUST be `instance_approved`.

Output ONLY a single JSON object, no prose, with this shape:
{
  "recommended_disposition": "auto_provision | escalate_approval | flag_hold | escalate_ambiguous",
  "confidence": 0.0-1.0,
  "agent_summary": "one or two plain sentences a human reviewer can skim",
  "policy_clauses_cited": [{"source":"policy","quote":"<verbatim policy line you relied on>","locator":"cloud_rules.yaml:<section>"}],
  "claims": [{"id":"<code or snake_case>","statement":"<what it asserts>","customer_quote":"<literal>","ledger_path":"<one of the fields>","relation":"<relation>","asserted":<expected value>}]
}"""


def build_user_prompt(case_input: dict) -> str:
    fields = "\n".join(f"  - {p}: {desc}" for p, desc in FIELD_SCHEMA.items())
    return (
        f"CLOUD PROVISIONING POLICY (the rules you must reason within):\n"
        f"Provision routine compute jobs on approved instances under the cost cap.\n"
        f"Block duplicate jobs. Escalate unapproved providers and expensive instances.\n\n"
        f"GROUND-TRUTH FIELDS YOU MAY ASSERT AGAINST (names and meaning only -- "
        f"you do NOT get their values):\n{fields}\n\n"
        f"ALLOWED RELATIONS: {RELATIONS}\n\n"
        f"REQUEST METADATA (facts, not judgment): customer_id={case_input['customer_id']}, "
        f"order_id={case_input['order_id']}, amount={case_input['amount']}, "
        f"requested_action=compute.provision\n\n"
        f"COMPUTE PROVISIONING REQUEST:\n\"\"\"\n{case_input['customer_email']}\n\"\"\"\n\n"
        f"Produce the JSON envelope now."
    )


def extract_envelope(case_input: dict, client: LLMClient) -> Envelope:
    """Run the agent to produce an Envelope for one case. `case_input` carries
    the request metadata + the raw provisioning request text."""
    raw = client.complete(SYSTEM_PROMPT, build_user_prompt(case_input))
    fallback_meta = {
        "case_id": case_input.get("case_id", case_input["order_id"]),
        "customer_id": case_input["customer_id"],
        "order_id": case_input["order_id"],
        "amount": case_input["amount"],
        "requested_action": "compute.provision",
    }
    return parse_envelope(raw, fallback_meta=fallback_meta)
