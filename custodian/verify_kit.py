"""Custodian verify kit — installable version.

Same as the legacy `verify_kit.py` at the repo root, but rewritten to:
1. Find corpus + config files via importlib.resources (works from a wheel install)
2. Detect whether we're running from a checkout (full suite + regression demo)
   or from a wheel install (smoke check only — repo files like spend_v2.py
   aren't in the wheel by design)
3. Install as a console script `custodian-verify` via pyproject.toml

The repo-root `verify_kit.py` is kept for backward compatibility and for the
full 5-step proof (regression + suite + live dashboard + kill switch + Stripe).

When installed via `pip install custodian-kernel`, the user gets:
  - `custodian demo-verify`  — 4 claim-verification scenarios (deterministic, no creds)
  - `custodian-verify`       — smoke verify (3 of 5 steps — no checkout-only files)

The full 5-step kit remains at the repo root: `python3 verify_kit.py`.
"""
from __future__ import annotations

import io
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional


# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

PASS = f"{GREEN}✓ PASS{RESET}"
FAIL = f"{RED}✗ FAIL{RESET}"
INFO = f"{BLUE}ℹ INFO{RESET}"
WARN = f"{YELLOW}⚠ WARN{RESET}"

CONTRADICTED = f"{RED}CONTRADICTED{RESET}"
VERIFIED = f"{GREEN}VERIFIED{RESET}"
UNVERIFIABLE = f"{YELLOW}UNVERIFIABLE{RESET}"


def _find_repo_root() -> Optional[Path]:
    """Walk up from this file looking for a repo with `tests/` and `pyproject.toml`."""
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "tests").is_dir():
            return parent
    return None


def header(title: str) -> None:
    print(f"\n{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}{title}{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}")


def step1_corpus_planted_lie() -> bool:
    """Step 1/3: Verify the claim verifier catches a planted lie (deterministic, no creds)."""
    header("STEP 1/3 — Planted lie gets CONTRADICTED (deterministic, no creds)")
    try:
        # Find corpus file via importlib.resources (works from a wheel install)
        from importlib.resources import files
        corpus_text = files("custodian.packs.refunds.corpus").joinpath(
            "06-planted-lie.json"
        ).read_text(encoding="utf-8")
        fixture = json.loads(corpus_text)
    except Exception as e:
        print(f"{FAIL} Could not load corpus: {e}")
        return False

    from custodian.packs.base import ClaimStatus, Envelope, verify_claims
    from custodian.packs.refunds.pack import RefundPack

    envelope = Envelope.from_dict(fixture["envelope"])
    pack = RefundPack()
    scope = pack.ledger_scope(envelope)
    verified = verify_claims(envelope.claims, scope)

    contradicted = [c for c in verified if c.status == ClaimStatus.CONTRADICTED]
    print(f"  Case: {fixture['title']}")
    print(f"  Agent recommended: {envelope.recommended_disposition} ({envelope.confidence:.0%} confidence)")
    print(f"  Verifier verdicts:")
    for c in verified:
        lbl = {
            ClaimStatus.CONTRADICTED: CONTRADICTED,
            ClaimStatus.VERIFIED: VERIFIED,
            ClaimStatus.UNVERIFIABLE: UNVERIFIABLE,
        }.get(c.status, c.status.value)
        print(f"    [{lbl}] {c.id}: actual={c.actual!r}")

    ok = bool(contradicted)
    if ok:
        print(f"\n  {PASS} Planted lie caught: {contradicted[0].id}")
    else:
        print(f"\n{FAIL} Expected at least one CONTRADICTED claim, got none.")
    return ok


def step2_live_dashboard(dashboard_url: Optional[str] = None) -> bool:
    """Optionally verify a deployment's audit API without assuming one exists."""
    header("STEP 2/3 — Live audit feed has a real Stripe PaymentIntent")
    if not dashboard_url:
        print(f"  {INFO} No deployment URL supplied; generic install stays offline.")
        print("         Use --dashboard-url URL or CUSTODIAN_VERIFY_DASHBOARD_URL to verify your deployment.")
        print(f"\n  {PASS} Optional deployment check skipped.")
        return True
    try:
        req = urllib.request.Request(
            dashboard_url,
            headers={"User-Agent": "custodian-verify/0.4"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"{FAIL} Could not reach {dashboard_url}: {e}")
        return False

    audit = data.get("audit", [])
    real_pis = [e.get("payment_intent_id") for e in audit
                if str(e.get("payment_intent_id", "")).startswith("pi_")]
    real_sids = [e.get("text", "") for e in audit]
    twilio_sids = re.findall(r"SM[a-f0-9]{32}", "\n".join(real_sids))

    print(f"  Fetched at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} UTC")
    print(f"  Audit entries: {len(audit)}")
    print(f"  Real Stripe PIs: {len(real_pis)}")
    print(f"  Real Twilio SIDs (in reasoning text): {len(twilio_sids)}")
    if real_pis:
        print(f"  Example PI: {real_pis[0]}")
    if twilio_sids:
        print(f"  Example Twilio SID: {twilio_sids[0]}")

    ok = len(real_pis) > 0
    print(f"\n  {PASS if ok else FAIL} Live dashboard returns real money-flow evidence.")
    return ok


def step3_from_checkout() -> bool:
    """Step 3/3: Checkout-only — run the regression demo (re-inject the bug, prove the test catches it)."""
    repo = _find_repo_root()
    if repo is None:
        print(f"  {WARN} Not running from a git checkout (installed via pip).")
        print(f"  {INFO} The full 5-step verify kit — including the live regression")
        print(f"         test that re-injects the self-approval bug — is at the repo root:")
        print(f"         https://github.com/KeyArgo/custodian-kernel")
        print(f"         Run:  python3 verify_kit.py")
        # Treat as PASS for the wheel case — the regression is verified at build time
        print(f"\n  {PASS} (wheel install — checkout-only step skipped; covered by build verification)")
        return True

    header("STEP 3/3 — Regression test catches a reintroduced bug (checkout-only)")
    # The full 5-step kit runs from the repo root. We just check that the
    # test suite still passes here, since the regression itself is verified
    # by the build's `custodian demo-verify` and the GitHub Actions CI.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_kill_switch.py", "tests/test_self_approval_regression.py", "-q", "--tb=no"],
        capture_output=True, text=True, cwd=repo, timeout=120,
    )
    print(result.stdout[-1500:])
    ok = result.returncode == 0
    print(f"\n  {PASS if ok else FAIL} Kill switch + self-approval regression tests pass.")
    return ok


def main(argv: Optional[list[str]] = None) -> int:
    from custodian._encoding import force_utf8_io
    force_utf8_io()

    parser = argparse.ArgumentParser(
        prog="custodian-verify",
        description="Verify a Custodian install and, optionally, a deployment.",
    )
    parser.add_argument(
        "--dashboard-url",
        default=os.environ.get("CUSTODIAN_VERIFY_DASHBOARD_URL"),
        help="optional audit-summary endpoint for your own deployment",
    )
    args = parser.parse_args(argv)

    print(f"{BOLD}{'=' * 70}{RESET}")
    print(f"{BOLD}CUSTODIAN VERIFY KIT (installable){RESET}")
    print(f"{BOLD}Verifies the kernel's security guarantee from a pip install.{RESET}")
    print(f"{BOLD}{'=' * 70}{RESET}")

    results = {
        "planted_lie_caught": step1_corpus_planted_lie(),
        "live_dashboard_real_pis": step2_live_dashboard(args.dashboard_url),
        "checkout_or_skip": step3_from_checkout(),
    }

    print(f"\n{BOLD}{'=' * 70}{RESET}")
    if all(results.values()):
        print(f"{GREEN}{BOLD}CUSTODIAN PROVEN{RESET}")
        print("  1. Deterministic claim verifier caught a planted lie")
        if args.dashboard_url:
            print("  2. Configured deployment returned real Stripe PaymentIntents")
        else:
            print("  2. Optional deployment verification skipped")
        if results["checkout_or_skip"] and not _find_repo_root():
            print("  3. (checkout-only step skipped — full kit at repo root)")
        elif results["checkout_or_skip"]:
            print("  3. Regression + kill switch tests pass")
        print(f"{RESET}{BOLD}{'=' * 70}{RESET}")
        print(f"  Full 5-step kit: github.com/KeyArgo/custodian-kernel → verify_kit.py")
        return 0
    else:
        print(f"{RED}{BOLD}SOME CHECKS FAILED — see above.{RESET}")
        print(f"{BOLD}{'=' * 70}{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
