---
name: stripe-subscription-cancel
description: "Cancel a Stripe subscription immediately or at period end"
version: 1.0.0
author: custodian
license: MIT
platforms: [linux, darwin, windows]
metadata:
  hermes:
    tags: [Stripe, Finance, Subscriptions]
  custodian:
    band: L3
    cost_usd: 0.0
    configured: false
---

# Stripe Subscription Cancel

Cancel a Stripe subscription immediately or at period end

## Authority band

This tool runs under **L3** authority in the Custodian kernel. Always requires human approval via Twilio SMS before executing.

## Inputs

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| (see execute.py for full schema) | | | |

## Configuration

Set the required environment variables before use. Until configured, `custodian tools run stripe-subscription-cancel` returns a stub response indicating which variables are needed.

## Usage

```bash
custodian tools run stripe-subscription-cancel --param value
```

## Custodian governance

Every call to this tool passes through the Custodian kernel authority check
before executing. The kernel verifies the current authority band, checks
spending caps where applicable, logs the action to the OCSF audit trail,
and escalates to a human operator if the action exceeds the declared band.

Adding this tool to any Hermes agent session requires no code changes —
declare `custodian-band: L3` in the SKILL.md frontmatter and the kernel
wraps it automatically.
