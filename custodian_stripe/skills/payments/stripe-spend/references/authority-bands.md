# Authority bands

Hermes operates under a bounded-authority model. Each band defines how much the agent can spend
**on its own**, and the point at which it must stop and ask a human.

| Band | Per-action cap | Session cap | Behavior |
|------|----------------|-------------|----------|
| L0   | $0.00          | $0.00       | Observe/estimate only. No spend capability. |
| L1   | $0.25          | $2.00       | Can plan and quote. Tiny reversible spends only. |
| L2   | $2.00          | $10.00      | **Active band for this demo.** Acts alone on routine, reversible, low-cost actions. |
| L3   | $2.01+         | any         | Exceeds L2 — requires explicit human approval before the Stripe call is made. |
| L4   | n/a            | n/a         | Human-only. Hermes never calls Stripe directly in this band. |

The active band is **L2**, recorded in `state/authority.json`. `scripts/spend.py` reads that file
on every call — do not hardcode the cap in conversation, always defer to the script's decision.

Crossing from L2 into L3 is not a failure. It is the system working correctly: the agent knew its
own limit and stopped before spending past it.
