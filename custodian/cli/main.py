from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path


_WELCOME = """
  Welcome to Custodian.

  Custodian is a safety check for AI assistants that can spend money.
  Before the AI spends anything, Custodian decides whether to allow it —
  small amounts go through, bigger ones wait for a human to say yes.

  Here are the first three things to do. Type them one at a time:

    1.  Set up (do this once)
          custodian init

    2.  Try a small request
          custodian request --amount 5 --description "a test"

    3.  See what happened
          custodian status

  Using Hermes Agent? Add Talaria (secrets/file/tool guardrails for it):
          custodian setup --profile hermes

  Want a friendly, step-by-step walkthrough?   Type:   custodian guide
  Want the full list of commands?              Type:   custodian help
"""

_GUIDE = """
  Custodian — a friendly walkthrough
  ==================================

  WHAT IS THIS?
    When an AI assistant can spend money (buy credits, pay for a service),
    someone has to decide what's allowed. Custodian is that decision-maker.
    The AI asks; Custodian answers "yes, go ahead" or "this one needs a
    human". You are the human.

  STEP 1 — Set up your workspace (once)
    Type:   custodian init
    This creates a folder that remembers your settings and keeps a log.

  STEP 2 — Make a request
    Type:   custodian request --amount 5 --description "buy API credits"
    A small amount is approved right away. Try a big one to see the
    difference:
            custodian request --amount 500 --description "big purchase"
    That one is held for a human to approve — on purpose.

  STEP 3 — Check the log
    Type:   custodian status      (your current limits and spending)
    Type:   custodian audit       (the full history, every decision)

  THE EMERGENCY STOP
    Type:   custodian kill --by yourname
    Nothing can be spent until you type:
            custodian resume --by yourname

  KEEP YOUR HISTORY SAFE
    Type:   custodian backup
    That saves your settings and full history into one file. Moving to a
    new computer, or something went wrong? Bring it all back with:
            custodian restore <the backup file>
    (Stored passwords/keys are separate — back those up with: paladin backup)

  THAT'S IT.
    You now know the whole tool. Everything else is a variation of these.
    Stuck? Type   custodian help   for the full list, or read the guide at
    https://github.com/KeyArgo/custodian-kernel
"""


def _print_welcome() -> int:
    print(_WELCOME)
    return 0


def _run_menu() -> int:
    from custodian.cli.menu import run_menu
    return run_menu()


def _print_guide() -> int:
    print(_GUIDE)
    return 0


class _FriendlyParser(argparse.ArgumentParser):
    """Turns argparse's terse errors into plain-language help with a
    'did you mean' suggestion — so a first-time user is never left staring
    at 'invalid choice' or a raw usage dump."""

    def error(self, message: str):
        suggestion = ""
        if "invalid choice:" in message:
            typed = message.split("invalid choice:")[1].split("'")[1] if "'" in message else ""
            choices = []
            for action in self._actions:
                if action.choices:
                    choices.extend(action.choices)
            near = difflib.get_close_matches(typed, list(choices), n=1, cutoff=0.5)
            if near:
                suggestion = f"\n\nDid you mean:   custodian {near[0]}"
        sys.stderr.write(f"\nSorry — {message}{suggestion}\n\n"
                         "Type   custodian help   to see everything Custodian can do,\n"
                         "or     custodian guide  for a friendly walkthrough.\n")
        raise SystemExit(2)

from custodian.cli import (
    cmd_init, cmd_validate, cmd_status, cmd_audit, cmd_request, cmd_approve,
    cmd_deny, cmd_kill, cmd_resume,
)
from custodian.cli import cmd_tools, cmd_demo_verify, cmd_earn_and_buy
from custodian.cli import cmd_status_enhanced, cmd_poison_tests, cmd_beancount, cmd_confirm
from custodian.cli import cmd_demo_receipt, cmd_generate_report
from custodian.cli import cmd_adapters
from custodian.cli import cmd_backup
from custodian.cli import cmd_setup, cmd_doctor
from custodian.cli import cmd_executor
from custodian.cli import cmd_console
from custodian.cli import cmd_codex_guard
from custodian.cli._version import LazyVersionAction
from custodian.config import CustodianConfig
from custodian.tools.registry import _state_dir as _codex_guard_state_dir


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

BACKUP & MIGRATION
  custodian backup                             workspace + history → one .zip
  custodian restore <file>                     bring it back, here or elsewhere
  paladin backup                               encrypted vault + audit trail
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
  python3 verify_kit.py                        5-phase self-verifying proof:
                                               re-introduces the self-approval bug,
                                               runs 1,747 tests, pulls live Stripe
                                               data, tests the kill switch end-to-end.

DEMO COMMANDS (no credentials, no side effects)
  custodian demo verify                        4 claim-verification scenarios live
  custodian demo cycle                         full earn→gate→GPU spend→verify loop
  custodian demo attacks                       5 planted attacks caught by kernel
  custodian demo receipt                       @govern + SHA-256 receipt walkthrough

docs:    https://getcustodian.xyz
install: pip install custodian-kernel
"""


def _add_state_dir(p: argparse.ArgumentParser, default: str) -> None:
    p.add_argument("--state-dir", default=default, help="Path to kernel state directory")


def _add_policy(p: argparse.ArgumentParser, default: str) -> None:
    p.add_argument("--policy", default=default, help="Path to policy YAML file")


def main(argv: list[str] | None = None) -> int:
    from custodian._encoding import force_utf8_io
    force_utf8_io()

    env_defaults = CustodianConfig.from_env()

    parser = _FriendlyParser(
        prog="custodian",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action=LazyVersionAction)
    # Not required: bare `custodian` shows a warm welcome instead of an error.
    sub = parser.add_subparsers(dest="command", required=False)

    # ── guide / help (plain-language onboarding) ───────────────────────────────
    p = sub.add_parser("guide", help="A friendly, step-by-step walkthrough for first-time users")
    p.set_defaults(func=lambda args: _print_guide())
    p = sub.add_parser("help", help="Show the full list of commands and what they do")
    p.set_defaults(func=lambda args: (parser.print_help() or 0))

    p = sub.add_parser("menu", help="Interactive menu — no syntax to memorize")
    p.set_defaults(func=lambda args: _run_menu())

    # ── setup ─────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "setup",
        help="Install the components you need (paladin/talaria) in one step",
        description=(
            "Detects a local Hermes Agent install and orchestrates `pip install` "
            "for the components you want, so you don't need to learn multiple "
            "package names. Bare `custodian setup` only detects and reports — "
            "pass --with or --profile to actually install something."
        ),
    )
    p.add_argument(
        "--with", dest="with_", metavar="COMPONENTS", default=None,
        help="Comma-separated components to install, e.g. --with talaria",
    )
    p.add_argument(
        "--profile", default=None,
        help="Install a named bundle of components (choices: hermes, minimal)",
    )
    p.add_argument("--dry-run", action="store_true", help="Show what would be installed, do nothing")
    p.add_argument(
        "--skip-configure", action="store_true",
        help="Install packages only; do not install or enable the Hermes plugin",
    )
    p.set_defaults(func=cmd_setup.run)

    p = sub.add_parser(
        "doctor",
        help="Check that Custodian and optional integrations are ready to use",
    )
    p.add_argument(
        "--profile", choices=["hermes"], default=None,
        help="Require every component for this integration profile",
    )
    p.set_defaults(func=cmd_doctor.run)

    # ── init ──────────────────────────────────────────────────────────────────
    p = sub.add_parser(
        "init",
        help="Scaffold a new custodian workspace",
        description="Create a workspace directory with a policy.yaml, state store, and README.",
    )
    p.add_argument("--dir", default=".", help="Target directory (default: current directory)")
    p.add_argument(
        "--session-cap", type=float, default=None, metavar="USD",
        help=(f"Total spend allowed per session (default: ${cmd_init.DEFAULT_SESSION_CAP:.2f}). "
              "Bands in policy.yaml set the PER-ACTION cap; the session budget has no policy "
              "field, so it is set here."),
    )
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
    _add_state_dir(p, str(env_defaults.state_dir))
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

    # ── backup / restore ──────────────────────────────────────────────────────
    p = sub.add_parser(
        "backup",
        help="Save the workspace (policy + history) to one backup file",
        description=(
            "Bundle policy.yaml and the state directory into a single .zip. "
            "The database is snapshotted with SQLite's online-backup API, so the "
            "backup is consistent even if the kernel is mid-write. Credentials are "
            "NOT in here — they live in the paladin vault (see `paladin backup`)."
        ),
    )
    p.add_argument("dest", nargs="?", default=None,
                   help="Destination file or directory "
                        "(default: ~/custodian-backups/custodian-backup-<time>.zip)")
    p.add_argument("--force", action="store_true",
                   help="Overwrite the destination file if it exists")
    _add_state_dir(p, str(env_defaults.state_dir))
    _add_policy(p, str(env_defaults.policy_path))
    p.set_defaults(func=cmd_backup.run_backup)

    p = sub.add_parser(
        "restore",
        help="Restore a workspace from a `custodian backup` file",
        description=(
            "Rebuild policy.yaml and the state directory from a backup .zip — "
            "here or on a brand-new machine. An existing workspace is never "
            "silently replaced: without --force this refuses, and with --force "
            "the current files are first saved to a pre-restore-<time>.zip."
        ),
    )
    p.add_argument("source", help="The backup .zip created by `custodian backup`")
    p.add_argument("--force", action="store_true",
                   help="Replace the existing workspace (after saving it to a "
                        "pre-restore-<time>.zip)")
    _add_state_dir(p, str(env_defaults.state_dir))
    _add_policy(p, str(env_defaults.policy_path))
    p.set_defaults(func=cmd_backup.run_restore)

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
    p.add_argument("request_id", help="The request-id recorded in the audit log for this action")
    p.add_argument("--deadline", type=int, default=None, metavar="SECONDS",
                   help="Confirmation window in seconds (default: 60)")
    _add_state_dir(p, str(env_defaults.state_dir))
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
    _add_state_dir(p, str(env_defaults.state_dir))
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

    # ── executor (delegated execution) ────────────────────────────────────────
    cmd_executor.register(sub)
    # Console reads ApprovalStore/CapabilityStore/ReceiptChain -- the same
    # ~/.custodian (or $CUSTODIAN_STATE_DIR) location codex_guard/mcp_server.py
    # and the executor actually write to. `env_defaults.state_dir` is a
    # different, older default (./state, project-local) used by the
    # request/approve/deny/resume/kill band-approval commands -- passing it
    # here left the console pointed at an empty directory by default, showing
    # "No actions waiting" while real pending approvals piled up elsewhere.
    cmd_console.register(sub, str(_codex_guard_state_dir()))

    # ── codex-guard ───────────────────────────────────────────────────────────
    cg_parser = sub.add_parser(
        "codex-guard",
        help="Codex Guard receipt chain and diagnostics",
        description="Inspect the HMAC hash-chained audit log of Codex Guard decisions.",
    )
    cg_sub = cg_parser.add_subparsers(dest="codex_guard_command", required=True)

    cg_rec = cg_sub.add_parser(
        "receipts",
        help="Print the codex-guard receipt chain",
        description="Pretty-print the JSONL receipt chain for Codex Guard decisions.",
    )
    _add_state_dir(cg_rec, str(_codex_guard_state_dir()))
    cg_rec.add_argument(
        "--limit", type=int, default=50,
        help="Max receipts to show (default: 50; 0 or negative means all)",
    )
    cg_rec.add_argument(
        "--verify", action="store_true",
        help="Run chain verification before printing",
    )
    cg_rec.set_defaults(func=cmd_codex_guard.run)

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
    if getattr(args, "command", None) is None or not hasattr(args, "func"):
        # A human at a terminal gets the interactive menu; a pipe/script/CI
        # gets the (non-blocking) welcome text as before.
        if sys.stdin.isatty() and sys.stdout.isatty():
            return _run_menu()
        return _print_welcome()
    try:
        code = args.func(args)
        return code if isinstance(code, int) else 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
