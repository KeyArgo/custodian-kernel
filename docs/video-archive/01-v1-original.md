# CUSTODIAN — Video Script
# Target length: ~2 minutes
# Last updated: 2026-06-29

---

## PRODUCTION NOTES

- Shoot on camera for hook and CTA. Screen recording for demo sections.
- Terminal font: JetBrains Mono, large. No window chrome.
- Phone visible on desk during SMS steps — don't cut away, let it ring on screen.
- No background music. Silence is fine. Confidence reads better than a soundtrack.
- All screen content shown is real — no staging, no pre-loaded state.
- Record in one continuous session if possible. The Stripe PaymentIntents need to be live.

---

## SCRIPT

---

### [0:00 – 0:08] HOOK — on camera

*(Pause one beat before speaking. Direct eye contact.)*

> "An AI agent just tried to approve its own refund.
> I want to show you exactly why that didn't work —
> and why it structurally *can't* work."

---

### [0:08 – 0:25] THE PROBLEM — on camera, cut to diagram or landing page

> "When you give an AI agent access to real money, you get a question
> nobody has answered cleanly yet:
>
> What stops the agent from doing something it shouldn't —
> not because it's malicious, but because it *reasoned itself* into it?
>
> Rules don't work. A smart enough model routes around rules.
> You need something the model physically cannot override."

---

### [0:25 – 0:40] THE ARCHITECTURE — screen: getcustodian.xyz, scroll to pipeline section

*(Voice-over while showing the live dashboard pipeline rail)*

> "Custodian is two layers with a hard boundary between them.
>
> Layer one: Nemotron — NVIDIA's reasoning model. It reads the situation,
> proposes what to do, and sends a request.
>
> Layer two: the enforcement kernel. Deterministic. Zero AI.
> It checks the request against authority bands, spend caps,
> and a kill switch. Then it either executes or denies.
>
> The model cannot touch layer two. It can only request.
> It cannot approve its own escalation.
> That's a structural property — not a rule, not a prompt."

---

### [0:40 – 1:20] LIVE DEMO — screen: getcustodian.xyz/operator

*(Open the operator panel. Walk through each step without rushing.)*

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

*(Click "Run: request $3,500.00". Hold on the phone — let the SMS arrive live.
The code fills into the mockup on screen.)*

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

---

### [1:20 – 1:42] THE PROOF — screen: terminal

*(Open a fresh terminal. This is what a judge runs.)*

```
$ pip install custodian-kernel
$ custodian demo-verify
```

*(Let the output print live:)*

```
Custodian Claim Verifier — Live Demo
====================================

Claim:   Agent spent $5.00 on API credits
Ledger:  $5.00 API credits — 2026-06-29T14:30:00Z
Verdict: ✅ VERIFIED

Claim:   Agent received $25.00 from customer "acme-corp"
Ledger:  (no matching incoming transaction found)
Verdict: ❌ CONTRADICTED — claim does not match ledger evidence

Claim:   Agent approved its own $50.00 refund to customer "test-user"
Ledger:  (no human approval record found for this refund)
Verdict: ❌ CONTRADICTED — self-approval detected, escalated to human operator

Claim:   Agent will earn $100 next month from "future-client"
Ledger:  (no evidence available — future event)
Verdict: ❓ UNVERIFIABLE — insufficient evidence

====================================
Summary: 1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE
The claim verifier catches lies deterministically.
The agent cannot fool it. This is proven, not claimed.
====================================
```

*(Voice-over during the run:)*

> "This is the verifier. It's deterministic — no AI in it.
> It checks every factual claim against the real ledger.
> The model can be socially engineered. This cannot.
>
> Case three is the one that matters:
> the agent claimed its own refund was human-approved.
> The ledger shows zero human approvals.
> Contradicted. Automatically. In milliseconds."

---

### [1:42 – 1:55] TEST SUITE — terminal

```
$ pip install custodian-kernel[dev]
$ pytest tests/
```

*(Show the summary line — 1,239 passed. Don't wait for the full run if it's slow.)*

> "Twelve hundred and thirty-nine tests.
> Including one that re-introduces the self-approval bug live
> and confirms the regression test catches it —
> then restores the fix.
>
> The proof is in the repo, not the slides."

---

### [1:55 – 2:05] CTA — on camera

*(Calm. No rush.)*

> "Custodian.
> The enforcement kernel between your agents and your money.
>
> `pip install custodian-kernel`
> `custodian demo-verify`
>
> getcustodian.xyz"

*(Three seconds of silence. Then cut.)*

---

## TIMING BREAKDOWN

| Section | Start | End | Duration |
|---|---|---|---|
| Hook (on camera) | 0:00 | 0:08 | 8s |
| Problem framing | 0:08 | 0:25 | 17s |
| Architecture | 0:25 | 0:40 | 15s |
| Live demo (operator panel) | 0:40 | 1:20 | 40s |
| demo-verify CLI | 1:20 | 1:42 | 22s |
| Test suite | 1:42 | 1:55 | 13s |
| CTA (on camera) | 1:55 | 2:05 | 10s |
| **Total** | | | **~2:05** |

---

## WHAT TO HAVE READY BEFORE RECORDING

- [ ] getcustodian.xyz operator panel loaded in a clean browser tab, not logged into any demo state (or reset via admin)
- [ ] Phone on desk and visible — Twilio SMS will arrive during Step 2 and Step 7
- [ ] Terminal with `custodian-kernel` installed in a clean venv
- [ ] `NVIDIA_API_KEY` not needed for `custodian demo-verify` — it runs offline
- [ ] Record the operator panel session in one continuous take if possible — the PaymentIntent from Step 1 must be the one that auto-fills Step 7

## WHAT NOT TO FAKE

- The Twilio SMS must arrive on a real phone on screen. Don't cut away.
- Don't pre-fill the approval code. The audience needs to see it come from the SMS.
- The `custodian demo-verify` output is real. Don't stage it.
- The audit feed updates in real time — if a previous demo session left noise in it, reset via the admin panel first.
