"""Tests for custodian.packs.agent."""
from __future__ import annotations

import json

import pytest

from custodian.packs.agent import CapturedClient, EnvelopeParseError, parse_envelope
from custodian.packs.base import Envelope


def make_envelope_payload(**overrides) -> dict:
    data = {
        "case_id": "case-1",
        "customer_id": "cust-1",
        "order_id": "order-1",
        "amount": 39.0,
        "requested_action": "refund.create",
        "claims": [],
        "policy_clauses_cited": [],
        "recommended_disposition": "approve_recommended",
        "confidence": 0.88,
        "agent_summary": "Looks like a clean refund request.",
    }
    data.update(overrides)
    return data


class TestParseEnvelope:
    def test_valid_json_returns_envelope(self):
        raw = json.dumps(make_envelope_payload())
        assert parse_envelope(raw) == Envelope.from_dict(make_envelope_payload())

    def test_missing_required_field_raises_parse_error(self):
        raw = json.dumps(make_envelope_payload())
        broken = json.loads(raw)
        del broken["case_id"]
        with pytest.raises(EnvelopeParseError, match="missing required fields"):
            parse_envelope(json.dumps(broken))

    def test_no_json_object_raises_parse_error(self):
        with pytest.raises(EnvelopeParseError, match="no JSON object found"):
            parse_envelope("just freeform text, no braces here")

    def test_invalid_json_raises_parse_error(self):
        with pytest.raises(EnvelopeParseError, match="not valid JSON"):
            parse_envelope('{"case_id": "case-1", }')

    def test_trailing_prose_with_braces_does_not_break_parse(self):
        # Live bug 2026-07-05: despite "output ONLY a single JSON object, no
        # prose", the model sometimes echoes the schema example or adds
        # commentary after the real object -- and that trailing text often
        # contains more braces (e.g. quoting the system prompt's own shape
        # example). A greedy `\{.*\}` regex used to match from the first `{`
        # all the way to the LAST `}` in the whole response, splicing the
        # trailing junk onto the real object and raising JSONDecodeError --
        # every custom /triage submission that triggered this silently fell
        # back to a generic "escalate_ambiguous" placeholder, which read as
        # the demo always escalating rather than a parse failure.
        raw = (
            json.dumps(make_envelope_payload())
            + '\nLet me double check this matches the required shape: '
            + '{"recommended_disposition": "...", "claims": [...]} looks right.'
        )
        assert parse_envelope(raw) == Envelope.from_dict(make_envelope_payload())

    def test_markdown_fenced_json_with_trailing_commentary(self):
        raw = (
            "```json\n" + json.dumps(make_envelope_payload()) + "\n```\n"
            "I'm confident in this analysis. {note: not real JSON, just thinking out loud}"
        )
        assert parse_envelope(raw) == Envelope.from_dict(make_envelope_payload())

    def test_fallback_meta_fills_missing_optional_fields(self):
        raw = json.dumps(
            {
                "claims": [],
                "policy_clauses_cited": [],
                "recommended_disposition": "approve_recommended",
                "confidence": 0.88,
                "agent_summary": "Looks like a clean refund request.",
            }
        )
        envelope = parse_envelope(
            raw,
            fallback_meta={
                "case_id": "case-1",
                "customer_id": "cust-1",
                "order_id": "order-1",
                "amount": 39.0,
                "requested_action": "refund.create",
            },
        )
        assert envelope == Envelope.from_dict(make_envelope_payload())

    @pytest.mark.parametrize(
        ("field", "present_value", "fallback_value"),
        [
            ("case_id", "present-case", "fallback-case"),
            ("customer_id", "present-customer", "fallback-customer"),
            ("order_id", "present-order", "fallback-order"),
            ("amount", 41.0, 39.0),
            ("requested_action", "invoice.pay", "refund.create"),
        ],
    )
    def test_fallback_meta_does_not_override_present_fields(
        self,
        field: str,
        present_value: object,
        fallback_value: object,
    ):
        payload = make_envelope_payload(**{field: present_value})
        envelope = parse_envelope(json.dumps(payload), fallback_meta={field: fallback_value})
        assert getattr(envelope, field) == present_value

    def test_json_embedded_in_surrounding_text_is_extracted(self):
        raw = f"Model output follows:\n{json.dumps(make_envelope_payload())}\nEnd of response."
        assert parse_envelope(raw).case_id == "case-1"


class TestEnvelopeParseError:
    def test_is_a_value_error(self):
        assert issubclass(EnvelopeParseError, ValueError)


class TestCapturedClient:
    def test_live_is_false(self):
        assert CapturedClient(make_envelope_payload()).live is False

    def test_complete_returns_json_string(self):
        client = CapturedClient(make_envelope_payload())
        assert client.complete("system", "user") == json.dumps(make_envelope_payload())

    def test_name_contains_captured(self):
        client = CapturedClient(make_envelope_payload())
        assert "captured" in client.name

