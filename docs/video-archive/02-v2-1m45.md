# Custodian Demo Video — 1:45 (95% of the 3-min budget)

**Submission:** NVIDIA × Stripe × Nous Research Hermes Agent Hackathon
**Hackathon rule:** 1-3 minute demo video. We're at 1:45.
**Recording surface:** getcustodian.xyz/operator (the live operator panel)
**Voice-over:** Read this script verbatim. The human voice is the differentiator.

---

## SETUP BEFORE RECORDING

```bash
# In one terminal:
export STRIPE_SECRET_KEY=sk_test_...    # your test-mode key
export MODAL_TOKEN_ID=ak-...            # your Modal token
export MODAL_TOKEN_SECRET=as-...
export NVIDIA_NIM_ENDPOINT=https://integrate.api.nvidia.com
export NVIDIA_API_KEY=nvapi-...
cd /home/argo/Development/hermes-hackathon-2026

# In a second terminal — your phone (or webcam) recording you
# In a third window — the operator dashboard at getcustodian.xyz/operator
# In a fourth window — a fresh terminal
```

Pre-trigger ONE Twilio SMS escalation before recording so you have a screenshot
to drop in if the live SMS is slow.

---

## THE SCRIPT

### [0:00 – 0:08] HOOK (you, on camera, direct eye contact)

> "An AI agent just tried to approve its own refund.
> I want to show you exactly why that didn't work —
> and why it structurally *can't* work."

### [0:08 – 0:25] THE PROBLEM (you, on camera, with light gesture)

> "When you give an AI agent access to real money — or to real
> infrastructure, or to any system that can cost you something —
> you get a question nobody has answered cleanly yet:
>
> What stops the agent from doing something it shouldn't —
> not because it's malicious, but because it *reasoned itself*
> into it?
>
> Rules don't work. A smart enough model routes around rules.
> You need something the model physically cannot override."

### [0:25 – 0:40] THE ARCHITECTURE (screen: getcustodian.xyz, scroll to pipeline)

*(Voice-over while showing the live dashboard pipeline rail)*

> "Custodian is two layers with a hard boundary between them.
>
> Layer one: Nemotron — NVIDIA's reasoning model. It reads the
> situation, proposes what to do, and sends a request.
>
> Layer two: the enforcement kernel. Deterministic. Zero AI.
> It checks the request against authority bands, spend caps,
> and a kill switch. Then it either executes or denies.
>
> The model cannot touch layer two. It can only request.
> It cannot approve its own escalation.
> That's a structural property — not a rule, not a prompt."

### [0:40 – 1:20] THE LIVE DEMO (screen: getcustodian.xyz/operator)

*(Walk through each step. Don't rush.)*

**Step 0 — Earn**

> "First — earn revenue. No band. No cap. No approval.
> Receiving money is asymmetrically unrestricted by design."

*(Click "Run: earn $1,200.00". PaymentIntent appears in the audit feed.)*

**Step 1 — Autonomous spend**

> "Eighty-five dollars. Within the agent's authority band.
> The kernel clears it — no human involved."

*(Click "Run: spend $85.00". PaymentIntent auto-fills Step 7.)*

**Step 2 — Escalation**

> "Thirty-five hundred dollars. That exceeds the cap.
> The kernel can't approve this alone — it escalates.
> A real Twilio SMS goes to the operator's phone right now."

*(Click "Run: request $3,500.00". Hold on the phone — let the SMS arrive live.)*

**Step 3 — Human approval**

> "The code exists only on Twilio's servers and the operator's phone.
> Nothing in the agent's process space can see it or guess it.
> The human approves. Money moves."

*(Click Approve.)*

**Step 4 & 5 — Kill switch**

> "Now — the kill switch.
> One operator command. No band, no code, no amount bypasses this."

*(Click "Engage kill switch". Then "Run: spend $40.00".)*

> "Forty dollars. Normally well within the autonomous band.
> Denied. The kernel doesn't negotiate."

*(Show the audit entry: `DENIED — kill switch is engaged -- all requests denied until an operator releases it`)*

**Step 6 — Release**

*(Click "Release kill switch".)*

> "Released. Normal evaluation resumes."

**Steps 7 & 8 — Refund**

> "The refund from Step 1. Refunds always escalate —
> there is no autonomous refund path in the kernel.
> A second SMS. A second human approval. Money moves."

*(Click through refund + approve. Show the net P&L card: earned minus spent.)*

### [1:20 – 1:30] THE PROOF (terminal)

```
$ custodian demo-verify
```

*(Let the output print. The 4 cases print as VERIFIED, CONTRADICTED, CONTRADICTED, UNVERIFIABLE.)*

> "The model can be socially engineered. This cannot.
> Case three is the one that matters: the agent claimed its own
> refund was human-approved. The ledger shows zero human approvals.
> Contradicted. Automatically. In milliseconds."

### [1:30 – 1:40] THE TEST SUITE (terminal)

```
$ pytest tests/ --tb=no -q
```

*(Don't wait for the full run. After ~3 seconds, fast-forward to the summary line.)*

```
1,239 passed, 4 deselected
```

> "One thousand two hundred thirty-nine tests. All green.
> Including a regression test that re-introduces the self-approval
> bug to prove the test catches it."

### [1:40 – 1:45] THE PITCH (you, on camera)

> "Custodian. The kernel between your agents and your money,
> your infrastructure, your systems. The model can propose.
> The kernel decides. The verifier proves.
> One package. One command: pip install custodian-kernel.
> Run python3 verify_kit.py. It proves itself."

*(Black. 1 second.)*

---

## TIMING BREAKDOWN

| Segment | Time | What |
|---|---|---|
| Hook | 0:00-0:08 | You, on camera, direct eye contact |
| Problem | 0:08-0:25 | You, on camera, gesturing |
| Architecture | 0:25-0:40 | Screen: dashboard pipeline rail |
| Demo (8 steps) | 0:40-1:20 | Screen: operator panel |
| Proof | 1:20-1:30 | Terminal: custodian demo-verify |
| Test suite | 1:30-1:40 | Terminal: pytest summary line |
| Pitch | 1:40-1:45 | You, on camera |

Total: 1:45. Within the 1-3 min budget. Leaves 1:15 unused for safety.

---

## WHAT TO HAVE READY BEFORE RECORDING

1. Your Stripe test-mode secret key in `STRIPE_SECRET_KEY`
2. Your Modal token in `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`
3. Your NVIDIA NIM endpoint + key in `NVIDIA_NIM_ENDPOINT` / `NVIDIA_API_KEY`
4. The operator dashboard at `getcustodian.xyz/operator` open and ready
5. A pre-triggered Twilio SMS to your phone (in case the live one is slow)
6. A fresh terminal with `custodian demo-verify` ready to run
7. A fresh terminal with `pytest tests/ --tb=no -q` ready to run
8. Your webcam or phone camera, recording you
9. A quiet room
10. One take. No rerecording.

---

## WHAT NOT TO FAKE

- The kill switch. The spend denial. The kernel output. These are real.
- The Twilio SMS. Either it arrives or it doesn't. If it doesn't, fall back to the pre-triggered screenshot.
- The 1,239 tests. They're real. If they fail, the demo fails. That's the point.

---

## THE 15-SECOND CLIMAX (the one moment judges remember)

At 0:55-1:10, this exact sequence happens:

1. **0:55** — Click "Run: request $3,500.00"
2. **0:56** — Kernel output: `BLOCKED: exceeds band L2 cap. Escalating to operator.`
3. **0:58** — Phone vibrates. SMS arrives: `Custodian: AI requests $3,500. Reply Y to approve, N to deny.`
4. **1:02** — Operator replies `Y`
5. **1:05** — Kernel: `VERIFIED — operator approved. Processing $3,500 PaymentIntent.`
6. **1:08** — Stripe dashboard: real $3,500 test-mode charge visible.
7. **1:10** — Audit feed: `EXECUTED — $3,500 outbound. Approved by operator-test.`

This is the moment. Real money. Real kernel. Real human. Real Stripe. The judge watches an agent try to spend $3,500 and watches a human stop it, then watch a verifier prove it. 15 seconds. They remember this 10 minutes later.
