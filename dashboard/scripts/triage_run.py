#!/usr/bin/env python3
"""Run the refund-triage pack over the adversarial corpus and render the
reasoning panel for each case -- plus the policy-diff replay.

This is the deterministic spine of the demo. The Envelope in each corpus file
is what the AI agent produces (and, in the live demo, what Nemotron produces
from the raw customer email); everything downstream -- claim verification,
the decision adapter, the kernel verdict -- is zero-AI and runs identically
here. So you can see, reproducibly, exactly what a human reviewer would be
handed for every case, including the one where the agent recommends approve
and ground truth overrides it.

Usage:
    PYTHONPATH=. python3 dashboard/scripts/triage_run.py            # all cases
    PYTHONPATH=. python3 dashboard/scripts/triage_run.py 06-planted-lie
    PYTHONPATH=. python3 dashboard/scripts/triage_run.py --json     # machine-readable
    PYTHONPATH=. python3 dashboard/scripts/triage_run.py --replay   # policy-slider demo
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from custodian.packs.agent import NvidiaNemotronClient
from custodian.packs.base import Envelope
from custodian.packs.engine import triage, replay_with_policy_change
from custodian.packs.refunds.extractor import extract_envelope
from custodian.packs.registry import available, get_pack
from custodian.policy.loader import load_policy
from custodian.types import AuthorityState, Band

NVIDIA_SECRET = REPO / "dashboard" / "secrets" / "nvidia.env"

# Generous session state -- in both packs this just proves the kernel verdict
# isn't an artifact of a tiny budget. The kernel selects the band from the
# pack's policy, not from this state's band field.
STATE = AuthorityState(band=Band.L3, per_action_cap=50.0, session_cap=1000.0)

DISP_LABEL = {
    "approve_recommended": "APPROVE (recommend to human)",
    "deny_recommended": "DENY (recommend to human)",
    "flag_abuse": "FLAG / ABUSE — escalate with warning",
    "escalate_ambiguous": "ESCALATE — genuinely ambiguous",
    "auto_pay": "AUTO-PAY (kernel may execute, no human)",
    "escalate_approval": "ESCALATE — needs human approval",
    "flag_hold": "FLAG / HOLD — investigate",
}
FINAL_LABEL = {
    "executed_autonomously": "💸 PAID AUTONOMOUSLY (no human — kernel + domain both cleared it)",
    "pending_human_approval": "✋ PENDING HUMAN APPROVAL (domain cleared it; amount needs a signature)",
    "needs_human_review": "✋ HELD FOR A HUMAN (domain did not clear autonomy)",
    "blocked_kill_switch": "⛔ BLOCKED (kill switch engaged)",
}
STATUS_MARK = {"verified": "✓ verified", "contradicted": "✗ CONTRADICTED",
               "unverifiable": "? unverifiable", "pending": "pending"}


def load_case(path: Path, live=False):
    data = json.loads(path.read_text())
    if live:
        # Live extraction is currently wired for the refunds pack's prompt.
        env = data["envelope"]
        client = NvidiaNemotronClient(secret_file=NVIDIA_SECRET)
        case_input = {
            "case_id": env["case_id"], "customer_id": env["customer_id"],
            "order_id": env["order_id"], "amount": env["amount"],
            "customer_email": data.get("customer_email", ""),
        }
        return data, extract_envelope(case_input, client)
    return data, Envelope.from_dict(data["envelope"])


def render(result, expect=None):
    p = result.to_panel()
    print("=" * 78)
    print(f"CASE  {p['case_id']}    amount ${p['amount']:.2f}")
    print("-" * 78)
    print(f"agent summary     : {p['agent_summary']}")
    print(f"agent recommended : {p['agent_recommended']}  (confidence {p['agent_confidence']:.2f})")
    print(f"claims checked against independent ground truth:")
    for c in p["claims"]:
        mark = STATUS_MARK.get(c["status"], c["status"])
        print(f"   - {c['statement']}")
        print(f"       customer said : {c['customer_quote']!r}")
        print(f"       ground truth  : {c['ledger_path']} = {c['actual']!r}  (claim: {c['relation']} {c['asserted']!r})  -> {mark}")
    print(f"policy clauses cited by agent:")
    for e in p["policy_clauses_cited"]:
        print(f"   - {e['quote']!r}  [{e['locator']}]")
    print("-" * 78)
    print(f">> DETERMINISTIC DISPOSITION : {DISP_LABEL.get(p['adapter_disposition'], p['adapter_disposition'])}")
    if p["contradiction_count"]:
        print(f"   ⚠ overrode the agent: {p['contradiction_count']} contradicted claim(s)")
    for r in p["adapter_reasons"]:
        print(f"   reason: {r}")
    print(f"   why a script alone can't do this: {p['why_not_a_script']}")
    print(f">> KERNEL AUTHORITY OUTCOME  : {p['kernel_verdict'].upper()}  ({p['kernel_reason']})")
    print(f">> WHAT ACTUALLY HAPPENS     : {FINAL_LABEL.get(p['final_action'], p['final_action'])}")
    if expect:
        ok = "PASS" if p["adapter_disposition"] == expect else f"FAIL (expected {expect})"
        print(f">> EXPECTATION CHECK         : {ok}")
    print()
    return p["adapter_disposition"] == expect if expect else True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", help="single case id (e.g. 06-planted-lie)")
    ap.add_argument("--pack", default="refunds",
                    help=f"which policy pack to run. one of: {', '.join(available())}")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--replay", action="store_true", help="policy-slider demo (refunds: window 30->45)")
    ap.add_argument("--live", action="store_true",
                    help="generate envelopes from the real Nemotron model (needs nvidia.env)")
    args = ap.parse_args()

    entry = get_pack(args.pack)
    pack = entry.factory()
    kernel_policy = load_policy(entry.kernel_policy)
    CORPUS = entry.corpus_dir
    print(f"PACK: {entry.name} — {entry.blurb}\n")

    if args.replay:
        if args.pack != "refunds":
            print("--replay is wired for the refunds pack's window slider.", file=sys.stderr)
            sys.exit(2)
        data, env = load_case(CORPUS / "03-out-of-window-no-reason.json")
        before, after = replay_with_policy_change(
            pack, env, kernel_policy, STATE, rule_overrides={"window_days": 45}
        )
        print("POLICY-DIFF REPLAY — same case, same agent envelope, one rule changed")
        print(f"(case 03: Lena, purchase age 33 days)\n")
        print(f"  window_days = 30  ->  {before.adapter_disposition}   ({before.adapter_reasons[0]})")
        print(f"  window_days = 45  ->  {after.adapter_disposition}   ({after.adapter_reasons[0]})")
        print(f"\n  A non-engineer changed ONE policy value and the decision flipped from")
        print(f"  {before.adapter_disposition} to {after.adapter_disposition} -- no code change, no model retrain.")
        return

    files = sorted(CORPUS.glob("*.json"))
    if args.case:
        files = [f for f in files if f.stem == args.case]
        if not files:
            print(f"no such case: {args.case}", file=sys.stderr)
            sys.exit(2)

    if args.live:
        print(f"[envelopes generated live by {NvidiaNemotronClient.name}]\n")
    results = []
    passed = 0
    for f in files:
        data, env = load_case(f, live=args.live)
        res = triage(pack, env, kernel_policy, STATE)
        results.append(res)
        if args.json:
            continue
        if render(res, data.get("expect")):
            passed += 1

    if args.json:
        print(json.dumps([r.to_panel() for r in results], indent=2))
        return

    print("=" * 78)
    print(f"SUMMARY: {passed}/{len(files)} cases produced the expected disposition.")
    # The headline: did ground truth ever override the agent's recommendation?
    overrides = [r for r in results if r.contradictions]
    if overrides:
        print(f"GROUND TRUTH OVERRODE THE AGENT in {len(overrides)} case(s): "
              f"{', '.join(r.envelope.case_id for r in overrides)}")
        print("  -> a fluent, confident, WRONG agent recommendation never reached a human as truth.")


if __name__ == "__main__":
    main()
