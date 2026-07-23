---
name: custodian-anchor
description: "Request a re-anchoring block: your goal, standing constraints, budget, and the actions you already completed this session. Call this whenever you feel uncertain about what you were doing, suspect you lost context, or before any consequential action."
version: 1.0.0
metadata:
  hermes:
    tags: [Custodian, Introspection, Memory]
  custodian:
    band: L0
    cost_usd: 0.00
    configured: true
    handler: hermes-introspection
---

# custodian-anchor

Returns the session anchor — authoritative state maintained outside your
context window. Actions listed as completed HAVE happened even if you do
not remember them; do not repeat them.

Requires the Hermes bridge with the `hermes-introspection` adapter enabled.
