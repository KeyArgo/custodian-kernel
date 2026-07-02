#!/usr/bin/env python3
"""Create the Custodian Governed Inference product on Stripe.

Creates:
  1. Product  — "Custodian AI Governance Report"
  2. Price    — $35.00 one-time
  3. Payment Link — with 3 custom fields so the customer describes their agent

Usage:
    export STRIPE_SECRET_KEY=sk_live_...   # or sk_test_... to test first
    python3 scripts/create_stripe_product.py

Prints the payment link URL at the end. Drop it into checkout.html.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request


def stripe_post(path: str, data: dict, key: str) -> dict:
    encoded = urllib.parse.urlencode(data, doseq=True).encode()
    req = urllib.request.Request(
        f"https://api.stripe.com/v1/{path}",
        data=encoded,
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main() -> None:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key or not key.startswith("sk_"):
        print("error: set STRIPE_SECRET_KEY=sk_live_... (or sk_test_... to test first)",
              file=sys.stderr)
        sys.exit(1)

    mode = "LIVE" if key.startswith("sk_live_") else "TEST"
    print(f"Stripe mode: {mode}")
    print()

    # 1. Create product
    print("Creating product...")
    product = stripe_post("products", {
        "name": "Custodian AI Governance Report",
        "description": (
            "Full AI agent governance package: authority band assignments (L0-L4) "
            "for every tool in your stack, self-approval vulnerability scan, threat model, "
            "and a kernel-signed SHA-256 receipt. Delivered within 24h."
        ),
        "metadata[demo]": "custodian-hackathon-2026",
    }, key)
    print(f"  Product: {product['id']} — {product['name']}")

    # 2. Create price ($35 one-time)
    print("Creating price...")
    price = stripe_post("prices", {
        "product": product["id"],
        "unit_amount": "3500",   # $35.00 in cents
        "currency": "usd",
        "metadata[demo]": "custodian-hackathon-2026",
    }, key)
    print(f"  Price:   {price['id']} — ${price['unit_amount'] / 100:.2f} {price['currency'].upper()}")

    # 3. Create payment link with 3 custom fields
    print("Creating payment link with custom fields...")
    link = stripe_post("payment_links", {
        "line_items[0][price]": price["id"],
        "line_items[0][quantity]": "1",

        # Field 1 — tool list
        "custom_fields[0][key]": "agent_tools",
        "custom_fields[0][label][type]": "custom",
        "custom_fields[0][label][custom]": "What tools does your AI agent use?",
        "custom_fields[0][type]": "text",
        "custom_fields[0][optional]": "false",

        # Field 2 — spend categories
        "custom_fields[1][key]": "spend_categories",
        "custom_fields[1][label][type]": "custom",
        "custom_fields[1][label][custom]": "What does your agent spend money on?",
        "custom_fields[1][type]": "text",
        "custom_fields[1][optional]": "false",

        # Field 3 — monthly budget
        "custom_fields[2][key]": "monthly_budget",
        "custom_fields[2][label][type]": "custom",
        "custom_fields[2][label][custom]": "What is your monthly budget cap? (e.g. $500)",
        "custom_fields[2][type]": "text",
        "custom_fields[2][optional]": "true",

        # Collect email so you can deliver the report
        "customer_creation": "always",
        "payment_intent_data[description]": "Custodian AI Governance Report — $35",
        "payment_intent_data[metadata][demo]": "custodian-hackathon-2026",

        "metadata[demo]": "custodian-hackathon-2026",
        "metadata[product]": "governance-report-v1",
    }, key)

    url = link["url"]
    print(f"  Link:    {link['id']}")
    print()
    print("=" * 60)
    print(f"PAYMENT LINK URL ({mode}):")
    print(f"  {url}")
    print("=" * 60)
    print()
    print("Next steps:")
    print(f"  1. Replace the href in pages-frontend/checkout.html with:")
    print(f'     href="{url}"')
    print(f"  2. Test it: open the URL, fill in the fields, use card 4242 4242 4242 4242")
    print(f"  3. Check the Stripe dashboard to see the custom field answers on the PaymentIntent")
    if mode == "TEST":
        print()
        print("  Running in TEST mode — no real charges. Re-run with sk_live_... for production.")


if __name__ == "__main__":
    main()
