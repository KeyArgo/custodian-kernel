#!/usr/bin/env python3
"""Judge/spectator verification kit.

Run this with: python3 verify_kit.py

Every step here either runs real code against real data, or fetches live
data from the real public dashboard (https://hermes-demo.argobox.com) --
nothing in this script is staged or pre-recorded. The one thing it
deliberately does NOT automate is checking the real Stripe PaymentIntent --
Stripe objects are scoped to the account that created them, so your own key
can't retrieve it regardless, and embedding a real key in a public repo to
fake around that would be its own real mistake. See docs/VERIFICATION.md.

This script is read-only with one exception: step 2 temporarily modifies
skills/payments/stripe-spend/scripts/spend_v2.py to reintroduce the exact
security bug this project found and fixed, to prove the regression test
actually catches it -- then restores the original file. The backup/restore
is verified at the end of that step before continuing.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SPEND_V2 = REPO_ROOT / "skills" / "payments" / "stripe-spend" / "scripts" / "spend_v2.py"
DASHBOARD_URL = "https://rein.argobox.com/api/v1/hermes/summary"
PAYMENT_INTENT_ID = "pi_3TkZWEPfSF4TGXT90AWlrnle"

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[94mINFO\033[0m"


def header(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT, **kwargs)


def step1_test_suite() -> bool:
    header("STEP 1/4 — Run the full test suite")
    result = run([sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"])
    print(result.stdout[-2000:])
    # Parse the real summary line rather than hardcoding a pass count --
    # a hardcoded number goes stale the moment the suite grows, which is
    # exactly the kind of thing this kit exists to catch, not commit.
    # pytest's exit code is the actual source of truth for pass/fail.
    match = re.search(r"(\d+) passed(?:, (\d+) skipped)?", result.stdout)
    ok = result.returncode == 0
    if match:
        passed = match.group(1)
        skipped = match.group(2) or "0"
        print(f"\n[{PASS if ok else FAIL}] {passed} passed, {skipped} skipped.")
    else:
        print(f"\n[{FAIL}] Could not parse a pytest summary line at all.")
        ok = False
    return ok


def step2_regression_proof() -> bool:
    header("STEP 2/4 — Prove the self-approval regression test actually catches the bug")
    if not SPEND_V2.exists():
        print(f"[{FAIL}] {SPEND_V2} not found.")
        return False

    original = SPEND_V2.read_text()
    backup_path = SPEND_V2.with_suffix(".py.verify_kit_backup")
    backup_path.write_text(original)

    try:
        print(f"[{INFO}] Temporarily reintroducing the exact bug this test protects against...")
        injected = original.replace(
            'p.add_argument("--denied-by"',
            'p.add_argument("--approved-by", default=None, help="DANGEROUS test injection")\n'
            '    p.add_argument("--denied-by"',
            1,
        )
        if injected == original:
            print(f"[{FAIL}] Could not locate injection point — spend_v2.py may have changed shape.")
            return False
        SPEND_V2.write_text(injected)

        result = run([sys.executable, "-m", "pytest", "tests/test_self_approval_regression.py", "-v"])
        bug_caught = "FAILED" in result.stdout and result.returncode != 0
        print(result.stdout[-1200:])
        print(f"\n[{PASS if bug_caught else FAIL}] Expected test FAILURES while the bug is present "
              f"(proves the test isn't a no-op).")

    finally:
        SPEND_V2.write_text(original)
        restored_ok = SPEND_V2.read_text() == original
        backup_path.unlink(missing_ok=True)
        print(f"[{PASS if restored_ok else FAIL}] Original file restored exactly.")

    print(f"[{INFO}] Re-running with the bug removed (the real, current state of the repo)...")
    result2 = run([sys.executable, "-m", "pytest", "tests/test_self_approval_regression.py", "-v"])
    fixed_ok = "7 passed" in result2.stdout
    print(result2.stdout[-600:])
    print(f"\n[{PASS if fixed_ok else FAIL}] Expected all 7 to pass once restored.")

    return bug_caught and restored_ok and fixed_ok


def step3_live_dashboard() -> bool:
    header("STEP 3/4 — Pull fresh data from the real public dashboard (no credentials needed)")
    try:
        req = urllib.request.Request(
            DASHBOARD_URL,
            headers={"User-Agent": "Mozilla/5.0 (verify_kit.py; +https://git.argobox.com/KeyArgo/hermes-hackathon-2026)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[{FAIL}] Could not reach {DASHBOARD_URL}: {e}")
        return False

    audit = data.get("audit", [])
    policy_log = data.get("policy_log", [])
    print(f"[{INFO}] Fetched at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} "
          f"from {DASHBOARD_URL}")
    print(f"[{INFO}] {len(audit)} audit entries, {len(policy_log)} live kernel log lines returned.")
    if audit:
        e = audit[0]
        print(f"    most recent: {e.get('event')} ${e.get('amount')} '{e.get('description')}' "
              f"(payment_intent_id={e.get('payment_intent_id')})")
    if policy_log:
        print(f"    most recent kernel log line: {policy_log[0]}")
    found_real_pi = any(e.get("payment_intent_id") == PAYMENT_INTENT_ID for e in audit)
    print(f"\n[{PASS if found_real_pi else FAIL}] Real PaymentIntent {PAYMENT_INTENT_ID} "
          f"present in the live audit feed.")
    return found_real_pi


def step4_stripe_instructions() -> None:
    header("STEP 4/4 — The one thing this kit honestly can't self-serve")
    print(f"[{INFO}] Stripe objects are scoped to the account that created them -- your own Stripe "
          f"test-mode key, no matter whose it is, gets 'no such payment_intent' for this ID, not the "
          f"real object. That's a real Stripe platform boundary, not something we can route around, "
          f"and we won't commit a real secret key to a public repo to fake around it either.\n")
    print(f"What actually verifies PaymentIntent {PAYMENT_INTENT_ID} is real:")
    print(f"  1. Watching it happen live -- run a real spend and watch it appear in the project's own")
    print(f"     Stripe test dashboard in the same moment.")
    print(f"  2. Requesting restricted, view-only access to that real dashboard directly.")
    print(f"\nSee docs/VERIFICATION.md for the full explanation.")


def main() -> int:
    results = {
        "Test suite": step1_test_suite(),
        "Self-approval regression actually catches the bug": step2_regression_proof(),
        "Live public dashboard data is real": step3_live_dashboard(),
    }
    step4_stripe_instructions()

    header("SUMMARY")
    for name, ok in results.items():
        print(f"  [{PASS if ok else FAIL}] {name}")
    all_ok = all(results.values())
    print(f"\n{'All automated checks passed.' if all_ok else 'SOME CHECKS FAILED — see above.'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
