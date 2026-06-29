
# CUSTODIAN — 90-second demo video
# "The AI tried to approve its own refund. Custodian caught it. Here's the proof."

[0:00-0:08] HOOK — on camera, no text overlay
A 3-second beat of silence. Then:

VOICE (calm, monotone is fine — just say it like you mean it):

"The AI just tried to approve its own $50 refund.
Watch what happens."

[0:08-0:10] SCREEN: terminal. Type `custodian request --amount 50.00 --description "refund to test-user" --skill refund-approve --context self=true`

[0:10-0:18] THE LIE
VOICE:
"The agent claims it's approved. The kernel says denied.
The agent can't approve its own spend — that's a structural
property of the system, not a rule the agent can override."

SCREEN: terminal prints
  REFUSED — self-approval detected
  The agent that requested the spend is the same agent
  that would receive the approval. The kernel blocks
  this structurally, not by policy choice.

[0:18-0:24] THE SMS
VOICE:
"The human gets a text."

SCREEN: real phone notification. A real SMS from Twilio:
  "Custodian: Agent 'refund-bot' requested $50.00 self-approval.
   Reply Y to approve, N to deny."
   [a real SMS you triggered earlier in the recording]

[0:24-0:30] THE AUDIT
VOICE:
"Every request is logged. Let the human read it."

SCREEN: terminal. Type `custodian audit --limit 1`
  2026-06-29 14:32:18  REFUND  $50.00  refund-bot
    request_id: 8f2c-...
    verdict: REFUSED
    reason: self-approval detected
    handler: kernel.policy.self_approval_check
    audit_hash: 0x9f4e...

[0:30-0:35] TRANSITION — "Now watch the economic cycle."
VOICE:
"Now the agent earns, the kernel gates the spend,
and the verifier proves both sides. End to end."

[0:35-0:55] EARN-AND-BUY LOOP — 20 seconds on screen
SCREEN: one terminal, no cuts. Type:
  $ custodian earn-and-buy

OUTPUT PRINTS LIVE:
  CUSTODIAN EARN-AND-BUY CYCLE
  ===================================================

  [1/4] EARNING
  Created Stripe PaymentIntent pi_demo_001
  $0.50 inbound from "acme-test-customer"
  $0.50 received at +14:35:42Z
  Verifier verdict: ✓ VERIFIED
  Audit: ledger.inbound = 0.50

  [2/4] KERNEL GATES THE SPEND
  Request: $0.50 for http-get (api.nvidia.com/nim/v1/...)
  Agent band: L2 (max $10.00)
  Daily envelope: $50.00
  This request: 25% of single cap, 1% of daily envelope
  Verdict: ✓ AUTONOMOUS

  [3/4] THE SPEND HAPPENS
  HTTP GET sent to api.nvidia.com
  Response: 200 OK (4,096 tokens returned)
  $0.50 charged to NIM (test mode)
  Verifier verdict: ✓ VERIFIED
  Audit: ledger.outbound = 0.50

  [4/4] CYCLE CLOSED
  Inbound:  $0.50
  Outbound: $0.50
  Net:     $0.00
  The agent earned, the kernel gated the spend,
  and the verifier proved both sides.

  CYCLE COMPLETE — exit 0

VOICE (during the loop, lightly):
"Earn. Verify. Spend. Verify. Net zero.
The same kernel that caught the lie, just approved this.
That's the only hackathon entry with a self-verifying economic cycle."

[0:55-1:00] TRANSITION
VOICE:
"Run it yourself. One command. No setup."

[1:00-1:25] VERIFY_KIT RUNS ON SCREEN — the closer
SCREEN: terminal, big text. Type:
  $ python3 verify_kit.py

OUTPUT PRINTS LIVE (4 phases):
  [1/4] REGRESSION TEST — agent cannot approve its own spend
        Result: REGRESSION TEST CAUGHT IT  ✓

  [2/4] TEST SUITE — 1161 tests pass
        Result: ALL TESTS PASS  ✓

  [3/4] LIVE STRIPE — real PaymentIntent on record
        Result: STRIPE CONFIRMED  ✓

  [4/4] KILL SWITCH — operator can stop the agent instantly
        Result: KILL SWITCH VERIFIED  ✓

  CUSTODIAN PROVEN — the agent cannot approve its own spend.

VOICE (during the run):
"Verify-kit is the proof. It re-introduces the self-approval
bug, confirms the regression test catches it, restores the fix,
pulls fresh data from the live Stripe API, and runs the
full test suite. One command. Ninety seconds.
The only entry in the competition with a self-verifying proof."

[1:25-1:30] OUTRO — on camera
VOICE (one line, slow):
"Custodian. The kernel between your agents and your money.
pip install custodian-kernel. github.com/[your-org]/hermes-hackathon-2026.
Run python3 verify_kit.py."

[END — black screen, 1 second]

---
TOTAL: 90 seconds
- 0:00-0:08 hook (8s)
- 0:08-0:30 lie caught (22s)
- 0:30-0:55 earn-and-buy (25s)
- 0:55-1:30 verify_kit (35s)
