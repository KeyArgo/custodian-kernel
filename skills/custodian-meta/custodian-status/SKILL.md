---
name: custodian-status
description: "Report your own governed session state: authority band, budget spent/remaining, action count, denial count. Value-free and instant — answered by the governance layer, no subprocess, no credentials. Use when unsure what you are allowed to do or how much budget remains."
version: 1.0.0
metadata:
  hermes:
    tags: [Custodian, Introspection]
  custodian:
    band: L0
    cost_usd: 0.00
    configured: true
    handler: hermes-introspection
---

# custodian-status

Returns your current session's enforced state. The numbers come from the
kernel, not from your memory — when they disagree with what you remember,
the kernel is right.

Requires the Hermes bridge with the `hermes-introspection` adapter enabled;
without it this skill does not exist.
