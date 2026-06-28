# Custodian — 90-Second Submission Video Script

**Target:** 90 seconds | **Format:** screen recording + voiceover | **Tone:** calm, precise, no hype

---

## Hook (0:00–0:10) — The problem

**Screen:** getcustodian.xyz landing page

> "AI agents are spending company money. Right now there's nothing stopping
> them from approving a refund because the customer was persistent —
> or because the customer lied. Prompt rules don't help. The agent writes them;
> the agent ignores them."

---

## Earn → Spend → Govern (0:10–0:32) — The closed loop

**Screen:** /operator — P&L bar visible at top reads EARNED $0 · SPENT $0 · NET $0.
Click **"⚡ Simulate Payment Received"**.
Navigate to /hermes — watch EARNED flip to +$25.00.
Watch audit feed: agent autonomously approves $8.50 NIM inference spend (L2 · autonomous).
P&L updates live: SPENT $8.50 · NET +$16.50 · MARGIN 66%.

> "A customer pays. The kernel logs it. The agent spends from those earned
> funds within its authority band — autonomously, under cap. Earned, spent,
> net. Every step in the audit trail. The agent never touched the accounting."

---

## Lie Catch (0:32–0:52) — The differentiator

**Screen:** /operator — type fraudulent claim into triage box:
*"I never received my order — I want a full refund"*

*Verdict panel appears: INCONSISTENT — Customer claims non-delivery; Stripe record shows delivered and signed.*
*Kernel badge: ESCALATE · L3 · Refunds always escalate.*

> "Every justification runs through a Nemotron fact-check before the kernel
> decides. The claim doesn't match the Stripe record. Refunds always escalate —
> the agent cannot override that. It's enforced below the prompt layer."

---

## Real Proof (0:52–1:08) — It's live

**Screen:** Open Stripe dashboard tab — zoom the live PaymentIntent ID.
Back to /hermes — engage kill switch. Attempt spend. Badge: BLOCKED · Kill switch active.

> "That's a live Stripe PaymentIntent — verify it yourself at Stripe's API.
> The SMS went to a real phone. The audit log is append-only.
> One command. Agent authority gone. Instantly."

---

## Scale (1:08–1:20) — 100 governed tools

**Screen:** /tools — filter to L3, show authority band breakdown

> "100 governed tools ship with Custodian — Stripe, NVIDIA NIM, shell exec,
> calendar, database. Each carries an authority band. Add one by adding
> one YAML line. The kernel governs everything in the same pipeline."

---

## Close (1:20–1:30)

**Screen:** getcustodian.xyz

> "Self-hosted. Model-agnostic. Swap the LLM; the enforcement doesn't move.
> getcustodian.xyz — running right now. Verify it yourself."

---

## Recording Notes

- Record at 1920×1080, 30fps
- Cursor: large, high-contrast (Keystroke Pro or similar)
- Real actions only — no cut/paste of fake API responses
- Voiceover: record separately, mix at -3dB
- Export: MP4 H.264, max 200MB for submission upload
- Backup: also export WebM for the site

## Timestamps to Hit

| Time | Action |
|---|---|
| 0:00 | Open getcustodian.xyz |
| 0:10 | Navigate to /operator |
| 0:13 | Click "⚡ Simulate Payment Received" |
| 0:16 | Navigate to /hermes — show P&L bar flip to EARNED $25.00 |
| 0:22 | Point to audit feed: EXECUTED · $8.50 · L2 autonomous |
| 0:28 | Point to P&L: NET +$16.50 · MARGIN 66% |
| 0:32 | Navigate to /operator — type fraudulent refund claim |
| 0:44 | Show INCONSISTENT verdict + ESCALATE badge |
| 0:52 | Open Stripe dashboard tab, zoom PaymentIntent |
| 0:58 | Back to /hermes — engage kill switch, show BLOCKED |
| 1:08 | Navigate to /tools, filter to L3 |
| 1:20 | Navigate to getcustodian.xyz |
| 1:28 | Fade out on live audit feed ticking |

## Pre-recording checklist

- [ ] Flask running on argobox-lite: `curl http://rein-local.argobox.com/api/v1/pnl/summary`
- [ ] Earn ledger is empty (fresh start): `ssh argonaut@100.81.234.88 "echo '' > /tmp/hermes-earn-ledger.json"`
- [ ] Triage page loads with pre-filled fraud scenario visible
- [ ] Kill switch confirmed OFF in operator panel
- [ ] Browser at 110% zoom for readability
- [ ] Stripe dashboard open in a separate tab, logged in
- [ ] Twilio SMS armed (real number in secrets env)
- [ ] Do one full dry run before recording
