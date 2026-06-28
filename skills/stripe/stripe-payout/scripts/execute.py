#!/usr/bin/env python3
"""Stub execute script for stripe-payout.

Replace this with a real implementation.
OpenCode prompt: custodian/opencode-prompts/stripe-tools.md
"""
import argparse, json, os, sys

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args, rest = p.parse_known_args()

    configured = bool(os.environ.get("STRIPE_PAYOUT_CONFIGURED"))
    if not configured:
        print(json.dumps({
            "ok": False,
            "stub": True,
            "tool": "stripe-payout",
            "message": "Set STRIPE_PAYOUT_CONFIGURED=1 (and required credentials) to enable.",
        }))
        sys.exit(0)

    # TODO: real implementation
    print(json.dumps({"ok": True, "tool": "stripe-payout", "result": "stub"}))

if __name__ == "__main__":
    main()
