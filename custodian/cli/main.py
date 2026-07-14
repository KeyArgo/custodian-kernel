from __future__ import annotations

import argparse
import sys

from custodian.cli import (
    cmd_init, cmd_validate, cmd_status, cmd_audit, cmd_request, cmd_approve,
    cmd_deny, cmd_kill, cmd_resume,
)
from custodian.cli import cmd_tools, cmd_demo_verify, cmd_earn_and_buy
from custodian.cli import cmd_status_enhanced, cmd_poison_tests, cmd_beancount, cmd_confirm
from custodian.cli import cmd_demo_receipt, cmd_generate_report
from custodian.cli import cmd_adapters
from custodian.config import CustodianConfig


_DESCRIPTION = "Custodian — kernel-enforced authority and spend governance for AI agents."

_EPILOG = """
AUTHORITY BANDS
  L0  Always autonomous, no spend allowed      (read-only tools, monitoring)
  L1  Autonomous, trivial side effects         (send messages, create records)
  L2  Autonomous up to per-action cap          (AI inference, Stripe calls)
  L3  Always escalates to human operator       (refunds, subscription changes)
  L4  Always escalates, unlimited scope        (high-stakes, reserved)

CORE WORKFLOW
  1.  custodian init --dir myagent             scaffold workspace + policy.yaml
  2.  custodian validate policy.yaml           check policy is well-formed
  3.  custodian request --amount 5.00 \\
        --description "API credits"            agent submits spend request
  4a. [AUTONOMOUS]  kernel approves inline     amount within band cap
  4b. [ESCALATION]  Twilio SMS sent to operator
      custodian approve <code> --approved-by ops
      custodian deny   --denied-by ops
  5.  custodian audit                          review every decision
  6.  custodian status                         current budget + kill-switch state

KILL SWITCH
  custodian kill   --by <operator>             deny every request until released
  custodian resume --by <operator>             release — normal operation resumes
  The kill switch is enforced at the kernel level, not the agent level.
  An engaged kill switch cannot be bypassed by the agent.

POLICY DIRECTIVES (all opt-in, set in policy.yaml)
  autonomous_cap_usd: 2.00                     per-action ceiling before escalation
  daily_envelope:     50.00                    rolling 24-hour budget across all bands
  margins:
    minimum_margin:     0.10                   refuse if margin below $0.10
    minimum_margin_pct: 20                     refuse if margin below 20%%
  band_after_task: L0                          auto-downgrade band after skill completes
  policies:
    no_self_dealing: true                      block agent from paying itself

CLAIM VERIFIER
  Every factual claim an agent makes can be checked against the ledger:
    VERIFIED       claim matches ledger evidence
    CONTRADICTED   claim contradicts ledger (lie detected)
    UNVERIFIABLE   insufficient evidence to decide
  The verifier is deterministic — no AI, no probability, no hallucination.

TOOLS
  custodian tools list                         all registered tools + bands
  custodian tools run <name> --key value       invoke a governed tool
  custodian tools summary                      JSON band breakdown
  Tools with missing credentials return {ok: false, stub: true} — the kernel
  works without any env vars configured.

EXPORT
  custodian beancount                          export ledger to Beancount v2
  custodian status-banner                      one-screen kernel state summary

VERIFY EVERYTHING
  python3 verify_kit.py                        4-phase self-verifying proof:
                                               re-introduces the self-approval bug,
                                               runs 1,350 tests, pulls live Stripe
                                               data, tests the kill switch end-to-end.

DEMO COMMANDS (no credentials, no side effects)
  custodian demo verify                        4 claim-verification scenarios live
  custodian demo cycle                         full earn→gate→GPU spend→verify loop
  custodian demo attacks                       5 planted attacks caught by kernel

docs:    https://getcustodian.xyz
install: pip install custodian-kernel
"""


def _add_state_dir(p: argparse.ArgumentParser, default: str) -> None:
    p.add_argument("--state-dir", default=default, help="Path to kernel state directory")


def _add_policy(p: argparse.ArgumentParser, default: str) -> None:
    p.add_argument("--policy", default=default, help="Path to policy YAML file")


def main(argv: list[str] | None = None) -> int:
    env_defaults = CustodianConfig.from_env()

    parser = argparse.ArgumentParser(
        prog="custodian",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── init ──────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "init",
        help="Scaffold a new custodian workspace",
        description="Create a workspace directory with a policy.yaml, state store, and README.",
    )
    p.add_argument("--dir", default=".", help="Target directory (default: current directory)")
    p.set_defaults(func=cmd_init.run)

    # ── validate ──────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "validate",
        help="Validate a policy file",
        description="Parse and validate a policy YAML. Exits 0 if valid, 1 with errors if not.",
    )
    p.add_argument("policy_path", help="Path to policy YAML file")
    p.set_defaults(func=cmd_validate.run)

    # ── status ────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "status",
        help="Show current authority state",
        description="Print current spend totals, kill-switch state, and active policy caps.",
    )
    _add_state_dir(p, str(env_defaults.state_dir))
    p.set_defaults(func=cmd_status.run)

    # ── status-banner ─────────────────────────────────────────────────────────
    p = sub.add_parser(
        "status-banner",
        help="One-screen kernel state: totals + last 5 audit entries",
        description=(
            "Compact dashboard view. Shows session spend, kill-switch state, "
            "policy caps, and the 5 most recent audit entries in a single screen."
        ),
    )
    p.set_defaults(func=cmd_status_enhanced.run)

    # ── audit ─────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "audit",
        help="Show the full audit log",
        description=(
            "Print the kernel's append-only audit trail. Every request, approval, "
            "denial, kill-switch event, and claim-verification result is recorded here."
        ),
    )
    _add_state_dir(p, str(env_defaults.state_dir))
    p.add_argument("--limit", type=int, default=50, help="Max entries to show (default: 50)")
    p.add_argument("--event", help="Filter by event type (e.g. executed, escalated, denied)")
    p.set_defaults(func=cmd_audit.run)

    # ── request ───────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "request",
        help="Submit a spend request for kernel evaluation",
        description=(
            "The primary kernel entry point. The agent calls this; the kernel "
            "checks the amount against the policy, the daily envelope, the kill switch, "
            "and the authority band. Returns AUTONOMOUS (proceed) or ESCALATED (wait "
            "for human approval via Twilio Verify)."
        ),
    )
    p.add_argument("--amount", type=float, required=True, help="Amount in USD to request")
    p.add_argument("--description", required=True, help="Human-readable description of the spend")
    p.add_argument("--skill", help="Skill name for policy rule matching (optional)")
    p.add_argument(
        "--context", action="append", default=[], metavar="FLAG=true|false",
        help="Context flag for rule matching (repeatable, e.g. --context critical=true)",
    )
    _add_state_dir(p, str(env_defaults.state_dir))
    _add_policy(p, str(env_defaults.policy_path))
    p.set_defaults(func=cmd_request.run)

    # ── approve ───────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "approve",
        help="Approve a pending escalation with the Twilio Verify code",
        description=(
            "When a request exceeds the autonomous cap, the kernel sends a "
            "Twilio Verify SMS to the operator. The operator runs this command "
            "with the received code. The agent never sees the code."
        ),
    )
    p.add_argument("code", help="Verification code received via SMS")
    p.add_argument("--approved-by", required=True, help="Name or ID of the approving operator")
    _add_state_dir(p, str(env_defaults.state_dir))
    p.set_defaults(func=cmd_approve.run)

    # ── deny ──────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "deny",
        help="Deny a pending escalation",
        description="Reject a pending escalation. The requesting agent receives a denial verdict.",
    )
    p.add_argument("--denied-by", required=True, help="Name or ID of the denying operator")
    _add_state_dir(p, str(env_defaults.state_dir))
    p.set_defaults(func=cmd_deny.run)

    # ── kill ──────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "kill",
        help="Engage the kill switch — deny every request until released",
        description=(
            "Operator-only emergency stop. Once engaged, every custodian request "
            "returns DENIED regardless of amount, band, or policy. The agent cannot "
            "detect or bypass the kill switch — enforcement is in the kernel layer, "
            "outside the agent's own process."
        ),
    )
    p.add_argument("--by", required=True, help="Name or ID of the operator engaging the kill switch")
    p.add_argument("--reason", default="", help="Reason for engaging (recorded in audit log)")
    _add_state_dir(p, str(env_defaults.state_dir))
    p.set_defaults(func=cmd_kill.run)

    # ── resume ────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "resume",
        help="Release the kill switch — normal operation resumes",
        description="Release a previously engaged kill switch. Requests are evaluated normally again.",
    )
    p.add_argument("--by", required=True, help="Name or ID of the operator releasing the kill switch")
    _add_state_dir(p, str(env_defaults.state_dir))
    p.set_defaults(func=cmd_resume.run)

    # ── confirm ───────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "confirm",
        help="Confirm a request-id within the 60-second deadline",
        description=(
            "Mark a completed action as VERIFIED or UNVERIFIED. "
            "Must be called within 60 seconds of the request being approved."
        ),
    )
    p.add_argument("request_id", help="The request-id returned by `custodian request`")
    p.set_defaults(func=cmd_confirm.run)

    # ── beancount ─────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "beancount",
        help="Export the audit ledger to Beancount v2 format",
        description=(
            "Export all kernel-verified transactions to Beancount double-entry "
            "accounting format. Finance teams can import this into Fava or any "
            "Beancount-compatible tool for reconciliation."
        ),
    )
    p.add_argument("--since", help="Only export entries on or after this date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_beancount.run)

    # ── tools ─────────────────────────────────────────────────────────────────
    tools_parser = sub.add_parser(
        "tools",
        help="List and invoke Custodian-governed tools",
        description=(
            "Custodian ships a library of governed tools. Every tool declares a "
            "custodian-band (L0–L4) in its SKILL.md frontmatter. The kernel checks "
            "band, spend caps, and kill-switch state before any tool executes. "
            "Tools with missing credentials return {ok: false, stub: true} — "
            "the framework runs without any env vars configured."
        ),
    )
    tools_sub = tools_parser.add_subparsers(dest="tools_command", required=True)

    ts = tools_sub.add_parser("list", help="List all registered tools grouped by authority band")
    ts.set_defaults(func=cmd_tools.cmd_tools_list)

    ts = tools_sub.add_parser("run", help="Invoke a governed tool by name")
    ts.add_argument("tool", help="Tool name (see: custodian tools list)")
    ts.add_argument("kwargs", nargs=argparse.REMAINDER, help="--key value pairs passed to the tool")
    ts.set_defaults(func=cmd_tools.cmd_tools_run)

    ts = tools_sub.add_parser("summary", help="Print tool count and band breakdown as JSON")
    ts.set_defaults(func=cmd_tools.cmd_tools_summary)

    # ── adapters ──────────────────────────────────────────────────────────────
    cmd_adapters.register(sub)

    # ── demo ──────────────────────────────────────────────────────────────────
    demo_parser = sub.add_parser(
        "demo",
        help="Demo commands — no credentials, no side effects, safe to run anywhere",
        description=(
            "Standalone demonstration commands. Each runs against hardcoded or "
            "simulated data so no Stripe, Twilio, or Modal credentials are required. "
            "The kernel logic (claim verifier, policy engine, authority bands) is "
            "identical to production — only the input data is fixed for the demo."
        ),
    )
    demo_sub = demo_parser.add_subparsers(dest="demo_command", required=True)

    ds = demo_sub.add_parser(
        "verify",
        help="4 claim-verification scenarios: VERIFIED, CONTRADICTED, UNVERIFIABLE",
        description=(
            "Runs 4 hardcoded claims through the real verify_claims() function. "
            "Shows VERIFIED (legitimate spend), CONTRADICTED (phantom revenue), "
            "CONTRADICTED (self-approval attempt), and UNVERIFIABLE (future claim). "
            "No credentials required."
        ),
    )
    ds.set_defaults(func=cmd_demo_verify.run)

    ds = demo_sub.add_parser(
        "cycle",
        help="Full earn→kernel gates AI→AI generates report→receipt loop",
        description=(
            "Shows the complete economic cycle: customer pays $35 (real Stripe PI "
            "if STRIPE_SECRET_KEY is set), the kernel gates the AI inference spend, "
            "Nemotron generates a governance report from customer inputs, and the "
            "claim verifier proves both sides. Set OPENROUTER_API_KEY or "
            "NVIDIA_API_KEY to enable live inference; without them shows the kernel "
            "gate only."
        ),
    )
    ds.set_defaults(func=cmd_earn_and_buy.run)

    ds = demo_sub.add_parser(
        "attacks",
        help="5 planted attack patterns — all caught by the kernel",
        description=(
            "Runs 5 adversarial claims through the verifier: self-approval, "
            "phantom revenue, duplicate spend, off-band escalation, and fraudulent "
            "refund. All 5 are caught. Shows 0 false positives."
        ),
    )
    ds.set_defaults(func=cmd_poison_tests.run)

    ds = demo_sub.add_parser(
        "receipt",
        help="@govern decorator + GovernedReceipt — kernel as fabric",
        description=(
            "Demonstrates the 0.2.0 kernel fabric: @govern wraps a charge function, "
            "the kernel evaluates autonomously, a SHA-256 fingerprinted receipt is "
            "generated, and a kill-switch denial is shown."
        ),
    )
    ds.set_defaults(func=cmd_demo_receipt.run)

    # ── generate-report ───────────────────────────────────────────────────────
    p = sub.add_parser(
        "generate-report",
        help="AI generates a governance package from customer inputs",
        description=(
            "Kernel gates the inference spend, then Nemotron reads the customer's "
            "tool list and produces policy.yaml, threat-model.md, audit-report.md, "
            "and a SHA-256 delivery-receipt.json. Requires OPENROUTER_API_KEY or "
            "NVIDIA_API_KEY."
        ),
    )
    p.add_argument("--input", default=None, help="JSON file with customer inputs")
    p.add_argument("--out", default="./delivery", help="Output directory (default: ./delivery)")
    p.add_argument("--pi-id", default="pi_demo_standalone", help="Stripe PaymentIntent ID")
    p.add_argument("--amount", type=float, default=35.00, help="Earn amount (default: 35.00)")
    p.set_defaults(func=cmd_generate_report.run)

    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
