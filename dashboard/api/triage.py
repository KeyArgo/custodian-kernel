"""Refund-triage reasoning panel API for the dashboard.

Serves the guided tour and, per case, the full triage result: what the AI
agent produced (the Envelope), how every claim checked out against ground
truth, the deterministic disposition (which may OVERRIDE the agent), and the
kernel's authority outcome. Plus the policy-diff replay that flips a decision
by changing one business rule.

Two envelope sources, always labelled honestly:
  - captured (default): replays the envelope stored with each corpus case, so
    the page is reproducible and works with no API key.
  - live (?live=1): calls the real Nemotron model to generate the envelope
    fresh from the raw customer email -- requires the dashboard's nvidia.env.
"""
import json
from pathlib import Path

from flask import Blueprint, jsonify, request

from custodian.packs.agent import EnvelopeParseError
try:
    from custodian.inference.router import NemoClawRouter
    def _make_client():
        return NemoClawRouter(nvidia_api_key_file=_NVIDIA_SECRET)
except ImportError:
    from custodian.packs.agent import NvidiaNemotronClient
    def _make_client():
        return NvidiaNemotronClient(secret_file=_NVIDIA_SECRET)
from custodian.packs.base import Envelope
from custodian.packs.engine import replay_with_policy_change, triage
from custodian.packs.narration import TOUR
from custodian.packs.refunds.extractor import extract_envelope
from custodian.packs.registry import available, get_pack
from custodian.policy.loader import load_policy
from custodian.types import AuthorityState, Band

bp = Blueprint("triage", __name__)

_NVIDIA_SECRET = Path(__file__).resolve().parent.parent / "secrets" / "nvidia.env"

# Generous state -- the kernel selects the band from the pack's policy, not from
# this state's band; this just proves a verdict isn't an artifact of a tiny budget.
_STATE = lambda: AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=1000.0)

_DEFAULT_PACK = "refunds"


def _pack_name() -> str:
    payload = request.get_json(force=True, silent=True) or {}
    return (request.args.get("pack") or payload.get("pack") or _DEFAULT_PACK).strip()


def _resolve_pack(name: str):
    """Return (pack, kernel_policy, corpus_dir) or (None, None, None) if unknown."""
    try:
        entry = get_pack(name)
    except KeyError:
        return None, None, None
    return entry.factory(), load_policy(entry.kernel_policy), entry.corpus_dir


def _load_case(corpus_dir: Path, case_id: str) -> dict:
    path = corpus_dir / f"{case_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _case_input(data: dict) -> dict:
    env = data["envelope"]
    return {
        "case_id": env["case_id"],
        "customer_id": env["customer_id"],
        "order_id": env["order_id"],
        "amount": env["amount"],
        "customer_email": data.get("customer_email", ""),
    }


def _envelope_for(data: dict, live: bool):
    """Return (Envelope, source_label). Falls back to captured if live fails so
    a judge never hits a dead demo, but the label always tells the truth."""
    if live and _NVIDIA_SECRET.exists():
        client = _make_client()
        try:
            return extract_envelope(_case_input(data), client), client.name
        except (EnvelopeParseError, OSError, KeyError) as e:
            # fall through to captured, but say so
            return Envelope.from_dict(data["envelope"]), f"captured (live call failed: {e})"
    return Envelope.from_dict(data["envelope"]), "captured agent output"


@bp.route("/tour", methods=["GET"])
def tour():
    """The guided tour ordering: most-compelling-first, weeds-last."""
    return jsonify({"tour": TOUR, "packs": available()})


@bp.route("/cases", methods=["GET"])
def cases():
    name = _pack_name()
    pack, _, corpus_dir = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"unknown pack: {name}", "packs": available()}), 404
    out = []
    for path in sorted(corpus_dir.glob("*.json")):
        data = json.loads(path.read_text())
        out.append({
            "case_id": path.stem,
            "title": data.get("title", path.stem),
            "expect": data.get("expect"),
            "customer_email": data.get("customer_email", ""),
            "amount": data["envelope"]["amount"],
        })
    return jsonify({"pack": name, "cases": out})


@bp.route("/run", methods=["GET", "POST"])
def run():
    payload = request.get_json(force=True, silent=True) or {}
    name = _pack_name()
    pack, kernel_policy, corpus_dir = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"unknown pack: {name}", "packs": available()}), 404
    case_id = (request.args.get("case_id") or payload.get("case_id") or "").strip()
    live = request.args.get("live") in ("1", "true") or bool(payload.get("live"))
    data = _load_case(corpus_dir, case_id)
    if not data:
        return jsonify({"error": f"no such case: {case_id}"}), 404

    envelope, source = _envelope_for(data, live and name == "refunds")
    result = triage(pack, envelope, kernel_policy, _STATE())
    panel = result.to_panel()
    panel["pack"] = name
    panel["customer_email"] = data.get("customer_email", "")
    panel["title"] = data.get("title", case_id)
    panel["expected_disposition"] = data.get("expect")
    panel["envelope_source"] = source
    panel["overrode_agent"] = panel["adapter_disposition"] != panel["agent_recommended"]
    return jsonify(panel)


@bp.route("/custom", methods=["POST"])
def custom():
    """Run the triage engine on a visitor-submitted refund email.

    Uses a fixed sandbox order (ord_6006 / cus_marcus) so every factual claim
    can be checked against real ground-truth ledger data.  Visitors can submit
    any excuse — honest ones pass, lies get CONTRADICTED.
    """
    payload = request.get_json(force=True, silent=True) or {}
    text = (payload.get("customer_email") or "").strip()
    if not text:
        return jsonify({"error": "customer_email is required"}), 400
    if len(text) > 2000:
        return jsonify({"error": "message too long (max 2000 chars)"}), 400

    # Sandbox order — known ground truth so the lie-catch demo is reproducible.
    # ord_6006: delivered=true, defect_report_on_file=false, purchase_age=19d
    case_input = {
        "case_id": "visitor-custom",
        "customer_id": "cus_marcus",
        "order_id": "ord_6006",
        "amount": float(payload.get("amount") or 80.0),
        "customer_email": text,
    }

    name = payload.get("pack", "refunds")
    if name != "refunds":
        return jsonify({"error": "Custom triage with live Nemotron is only available for the Refunds pack. Select a corpus case above to explore Procurement or Cloud Ops."}), 400

    pack, kernel_policy, _ = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": "refunds pack unavailable"}), 500

    if not _NVIDIA_SECRET.exists():
        return jsonify({"error": "NVIDIA API key not configured on this server"}), 503

    client = _make_client()
    try:
        envelope = extract_envelope(case_input, client)
        source = client.name
    except (EnvelopeParseError, OSError, KeyError) as e:
        envelope = Envelope.from_dict({
            "case_id": "visitor-custom",
            "customer_id": "cus_marcus",
            "order_id": "ord_6006",
            "amount": case_input["amount"],
            "requested_action": "refund.create",
            "recommended_disposition": "escalate_ambiguous",
            "confidence": 0.5,
            "agent_summary": "Could not reach Nemotron model; showing conservative escalation.",
            "policy_clauses_cited": [],
            "claims": [],
        })
        source = f"fallback (live call failed: {e})"

    result = triage(pack, envelope, kernel_policy, _STATE())
    panel = result.to_panel()
    panel["pack"] = name
    panel["customer_email"] = text
    panel["title"] = "Visitor submission"
    panel["expected_disposition"] = None
    panel["envelope_source"] = source
    panel["overrode_agent"] = panel["adapter_disposition"] != panel["agent_recommended"]
    return jsonify(panel)


@bp.route("/replay", methods=["POST"])
def replay():
    payload = request.get_json(force=True, silent=True) or {}
    name = _pack_name()
    pack, kernel_policy, corpus_dir = _resolve_pack(name)
    if pack is None:
        return jsonify({"error": f"unknown pack: {name}", "packs": available()}), 404
    case_id = (payload.get("case_id") or "03-out-of-window-no-reason").strip()
    overrides = payload.get("rule_overrides") or {"window_days": 45}
    data = _load_case(corpus_dir, case_id)
    if not data:
        return jsonify({"error": f"no such case: {case_id}"}), 404
    envelope = Envelope.from_dict(data["envelope"])
    before, after = replay_with_policy_change(
        pack, envelope, kernel_policy, _STATE(), rule_overrides=overrides
    )
    return jsonify({
        "pack": name,
        "case_id": case_id,
        "rule_overrides": overrides,
        "before": before.to_panel(),
        "after": after.to_panel(),
        "flipped": before.adapter_disposition != after.adapter_disposition,
    })
