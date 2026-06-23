# What This Actually Is

If you can only remember one sentence: **this lets you safely hand an AI agent a real
budget, by keeping the part that decides "is this worth it" completely separate from
the part that's allowed to say yes.**

## The two-layer mental model

There are two genuinely different things in this system, and confusing them is the
single biggest reason this has been hard to describe.

**Layer 1 — Custodian (the engine). No AI. Deliberately.**
This is plain, boring, deterministic code: spending caps, a human-approval gate via a
real text message, a kill switch, and a permanent log of everything that happened. None
of it involves a model "deciding" anything. It can't — that's the point. You do not
want fuzzy AI judgment anywhere near the actual safety boundary. If "should this be
allowed" were itself an AI decision, the whole system would be *less* trustworthy, not
more.

**Layer 2 — the agent (Hermes, running on Nemotron). All AI. Deliberately.**
This is the thing that looks at real, messy, ambiguous information and decides whether
something is even worth requesting in the first place. It has zero ability to approve
its own requests, zero ability to touch the kill switch, zero ability to see the
approval code that gets texted to a human. It can only ask. Layer 1 decides whether the
ask is honored.

**The whole point of the project is the gap between those two layers — not either one
alone.** A program that just enforces caps already exists in a dozen forms. An AI that
just makes judgment calls with no real consequence is a toy. The thing that's actually
hard, and actually new, is connecting a real AI's judgment to a real budget without
letting the AI anywhere near the part that keeps it honest.

## Walking through one real example, start to finish

This actually happened, with real consequences, during this build:

1. **The agent looks at real data** — actual disk usage and system status from a real
   homelab, not a script's canned check. (Layer 2.)
2. **It decides a $45 backup-software renewal is worth paying for**, based on reasoning
   about that real data — and explains why. (Layer 2. A script can't write a *reason*,
   it can only trip a threshold.)
3. **It asks Custodian.** Custodian checks: this amount is over the agent's spending
   cap. (Layer 1 — pure arithmetic, no judgment.)
4. **Custodian sends a real text message** with a one-time code to a human's actual
   phone — generated and held only by the verification provider's servers, never by
   anything the agent can read. (Layer 1.)
5. **The agent cannot do anything else.** There is no flag, no setting, no clever
   prompt that lets it skip this step. It has to wait. (This is the part we found a
   real bug in, fixed, and can prove stays fixed — see `docs/SECURITY.md`.)
6. **A human enters the real code.** Custodian checks it against the real verification
   service, not against anything stored locally. (Layer 1.)
7. **Only then does the real charge happen** — a real Stripe API call, a real object
   that exists on Stripe's own servers. (Layer 1 executes; Layer 2 never touches money
   directly, ever.)
8. **Everything is logged, permanently, including the parts that didn't go cleanly** —
   a code that expired before it was used, a later retry that worked. Nothing gets
   cleaned up or hidden. (Layer 1.)

## "Couldn't a normal program do all of this?"

Steps 3, 4, 6, 7, 8 above: yes, completely, and it should be a normal program — that's
Layer 1, and AI has no business being there.

Step 1-2: this is the one a script genuinely can't replicate, and we tested this
directly, not just asserted it. The clearest proof: we told the agent a fabricated
"crisis" was happening. It checked the real telemetry, found the data didn't support
the story, and refused to act on the narration. A fixed script can't do that — it can
only check what it's told to check. Recognizing that a *claim* and the *real data*
disagree, and siding with the data, requires actually interpreting information, not
matching a pattern.

## The one-sentence pitch

**"The first AI agent you can hand a real wallet to — not because it's trustworthy,
but because the part of the system that's allowed to spend money was deliberately
built so the AI can never get near it."**

## Common questions

**Is real money moving?** No — Stripe test mode. Real API calls, real objects that
exist on Stripe's servers, checkable, but no actual currency changes hands. See
`docs/VERIFICATION.md` for exactly what "real" does and doesn't mean here.

**How would a judge actually verify any of this?** Run `python3 verify_kit.py` — it
re-runs the real test suite, actually re-introduces and removes the found security bug
live to prove the fix holds, and pulls fresh data from the real public dashboard. See
`docs/VERIFICATION.md` for the full breakdown, including the one thing it honestly
can't self-serve (Stripe account-scoping) and why.

**What's the kill switch for, again?** An emergency stop a human can pull that
overrides everything else — every cap, every band, instantly — if something seems
wrong in a way the normal limits don't catch. The agent has no ability to set or clear
it. See the commit history for a real, live demonstration: a real charge succeeded,
the kill switch was engaged, the *exact same* request was denied by the real live
script, then released, then the real charge succeeded again.

**Why does the engine matter if the agent is the "smart" part?** Because an agent's
judgment is only useful if you can actually trust the consequences are bounded. Without
Layer 1, you'd have an interesting demo and no real reason to ever let it touch your
money.

## The honest path from demo to a real business

Today: single-tenant, Stripe test mode, one real proof-of-concept (the ops-officer).
That's intentionally what's been built and verified in this window — going further
wasn't the right use of the time available, not something we couldn't articulate.

The path to an actual operating business is concrete, not hand-wavy, and doesn't
require new invention:

1. **Multi-tenant policy storage.** `custodian/storage/sqlite.py` already isolates
   state per workspace (one `custodian.db` per `--state-dir`). Serving multiple real
   customers means one workspace per customer behind a real account system — an
   extension of the existing storage abstraction, not a redesign of it.
2. **Live Stripe mode.** The integration is already real, test-mode is a config flag,
   not a different code path — `custodian/backends/twilio_verify.py` and the Stripe
   calls in `_core.py` use the same API shape in test and live mode.
3. **A second, third, fourth real proof-of-concept**, chosen from
   `docs/BUSINESSES_THIS_UNLOCKS.md` — each one is a customer-facing product; Custodian
   is the thing every one of them licenses or runs on.
4. **Pricing**, once a real proof-of-concept has a real first customer: the natural
   shape is a platform fee for the enforcement layer (Custodian itself) plus usage-based
   revenue on whichever proof-of-concept app is actually deployed — i.e., license the
   trust primitive, sell the application built on top of it.

None of this is built. All of it is a direct extension of what's already real, not a
pivot away from it — which is the honest answer to "could this become a real
business": yes, and the next concrete step is named, not vague.
