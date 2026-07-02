#!/usr/bin/env python3
"""Debug: show exactly what Nemotron returns."""
import sys
sys.path.insert(0, ".")
from custodian.inference.router import NemoClawRouter
from custodian.cli.cmd_generate_report import _SYSTEM_PROMPT, _user_prompt

inputs = {
    "customer": "acme-test-customer",
    "agent_tools": "web_search, send_email, stripe_payments, read_file",
    "spend_categories": "Stripe payments, API calls",
    "monthly_budget": "$500",
}

router = NemoClawRouter(timeout=60)
print(f"Key: {(router._openrouter_key() or 'NONE')[:25]}...")
print("Calling...")
try:
    raw = router.complete(_SYSTEM_PROMPT, _user_prompt(inputs), max_tokens=12000)
    print(f"\n=== LAST 4000 chars of {len(raw)} total ===")
    print(raw[-4000:])
    print("\n=== END ===")
except Exception as e:
    print(f"Error: {e}")
