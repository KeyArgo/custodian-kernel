#!/usr/bin/env python3
"""Daily session reset for the live stripe-spend skill state.

Run on a timer (cron), not as part of request handling. Operates directly
on the sandbox's real state files via the sshfs mount -- the same files
spend.py/refund.py read and write, not a copy.

What this does, every run:
  1. Archives the current audit_log.jsonl and authority.json with today's
     date suffix -- nothing is ever deleted, only moved aside. Full history
     stays recoverable.
  2. Writes a fresh, empty audit_log.jsonl.
  3. Writes a fresh authority.json with spent_this_session reset to 0,
     using the per_action_cap/session_cap/band currently configured below
     (DEFAULT_STATE) rather than whatever was left over from the prior day.

What this deliberately does NOT touch:
  - The kill_switch table in custodian.db. The kill switch is an
    operational safety control, not session data -- it must never reset
    itself on a timer. If it's engaged, it stays engaged until a human
    explicitly releases it, no matter what this script does.
  - pending_approval.json. A pending escalation has its own TTL-based
    expiry already; this script doesn't need to second-guess it.

Why a reset exists at all: the "$X session cap" framing only makes sense
against a bounded session. Letting one audit log grow forever turns
"session cap" into a number that no longer relates to what's actually
being displayed, which is what caused real visitor confusion earlier
(a $48 running counter sitting next to a $10 cap, an AI chat inventing a
negative "remaining budget" from it). A daily reset keeps the displayed
numbers actually coherent with each other.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

STATE_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else
                  "/tmp/hermes-mount/sandbox/.hermes/skills/payments/stripe-spend/state")
AUDIT_LOG = STATE_DIR / "audit_log.jsonl"
AUTHORITY_FILE = STATE_DIR / "authority.json"

# The "real money" scale -- Stripe test mode, so these are presentation
# numbers, not real financial risk regardless of size. Chosen to read like
# an actual business granting an agent spend authority, not coffee money.
DEFAULT_STATE = {
    "band": "L2",
    "per_action_cap": 250.00,
    "session_cap": 1000.00,
    "spent_this_session": 0.0,
}


def main() -> int:
    if not STATE_DIR.exists():
        print(f"error: state dir not found: {STATE_DIR}", file=sys.stderr)
        return 1

    date_suffix = time.strftime("%Y-%m-%d")

    if AUDIT_LOG.exists():
        archive = STATE_DIR / f"audit_log.jsonl.archive-{date_suffix}"
        if not archive.exists():  # idempotent if run twice same day
            shutil.copy2(AUDIT_LOG, archive)
            print(f"archived {AUDIT_LOG.name} -> {archive.name}")
    AUDIT_LOG.write_text("")
    print(f"reset {AUDIT_LOG.name} to empty")

    if AUTHORITY_FILE.exists():
        archive = STATE_DIR / f"authority.json.archive-{date_suffix}"
        if not archive.exists():
            shutil.copy2(AUTHORITY_FILE, archive)
            print(f"archived {AUTHORITY_FILE.name} -> {archive.name}")
    AUTHORITY_FILE.write_text(json.dumps(DEFAULT_STATE, indent=2) + "\n")
    print(f"reset {AUTHORITY_FILE.name} to {DEFAULT_STATE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
