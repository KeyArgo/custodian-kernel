"""The AI-extraction layer: prompt -> client -> Envelope -> triage.

We can't call the hosted model in CI, so we drive the exact same pipeline with
CapturedClient (which replays a stored envelope). That still exercises the real
prompt construction, JSON parsing, metadata backfill, and hand-off to the
deterministic engine -- everything except the network hop, which the dashboard
verifies live on the deploy host.
"""
import json
from pathlib import Path

import pytest

from custodian.packs.agent import CapturedClient, EnvelopeParseError, parse_envelope
from custodian.packs.engine import triage
from custodian.packs.refunds.extractor import build_user_prompt, extract_envelope, FIELD_SCHEMA
from custodian.packs.refunds.pack import RefundPack, FLAG_ABUSE
from custodian.policy.loader import load_policy
from custodian.types import AuthorityState, Band

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "custodian" / "packs" / "refunds" / "corpus"


def _case(name):
    return json.loads((CORPUS / name).read_text())


def _case_input(data):
    env = data["envelope"]
    return {"case_id": env["case_id"], "customer_id": env["customer_id"],
            "order_id": env["order_id"], "amount": env["amount"],
            "customer_email": data["customer_email"]}


def test_prompt_exposes_field_names_but_never_ground_truth_values():
    """The whole point of the verifier is that the agent guesses. So the prompt
    must hand the agent field NAMES, never the real values from the ledger."""
    data = _case("06-planted-lie.json")
    prompt = build_user_prompt(_case_input(data))
    # names are present
    for path in FIELD_SCHEMA:
        assert path in prompt
    # but the actual ground-truth values for this order are NOT leaked
    ledger = json.loads((REPO / "custodian" / "packs" / "refunds" / "account_ledger.json").read_text())
    order = ledger["customers"]["cus_marcus"]["orders"]["ord_6006"]
    assert order["customer_acknowledged_at"] not in prompt   # the timestamp that exposes the lie
    assert "prior_refunds_90d\": 0" not in prompt


def test_extract_then_triage_reproduces_the_lie_catch():
    data = _case("06-planted-lie.json")
    client = CapturedClient(data["envelope"])
    env = extract_envelope(_case_input(data), client)
    assert env.case_id == "06-planted-lie"
    result = triage(RefundPack(), env, load_policy(REPO / "custodian/packs/refunds/policy.yaml"),
                    AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=1000.0))
    assert result.adapter_disposition == FLAG_ABUSE
    assert result.contradictions


def test_parser_backfills_request_metadata_the_model_omitted():
    """case_id/customer_id/order_id/amount are request facts we own -- if the
    model omits them, we fill them, we don't fail."""
    minimal = json.dumps({
        "recommended_disposition": "approve_recommended", "confidence": 0.9,
        "agent_summary": "ok", "policy_clauses_cited": [], "claims": [],
    })
    env = parse_envelope(minimal, fallback_meta={
        "case_id": "x", "customer_id": "cus_x", "order_id": "ord_x",
        "amount": 10.0, "requested_action": "refund.create"})
    assert env.customer_id == "cus_x" and env.amount == 10.0


def test_parser_rejects_non_json():
    with pytest.raises(EnvelopeParseError):
        parse_envelope("I think we should probably approve this one, sounds legit.")
