# Custodian — 90-Second Submission Video Script

**Target:** 90 seconds | **Format:** screen recording + voiceover | **Tone:** calm, precise, no hype

---

## Hook (0:00–0:12) — The problem

**Screen:** landing page hero, customer refund triage demo loading in background

> "AI agents are spending company money. Right now, there's nothing stopping
> an agent from approving a refund because the customer was persistent — or
> because the customer lied. Prompt rules don't help. The agent writes them;
> the agent ignores them."

---

## The Kernel (0:12–0:28) — What Custodian is

**Screen:** triage.html — live demo with the fraudulent refund scenario; show the audit trail panel

> "Custodian is an authority kernel. The agent submits a spend request. The
> kernel decides — autonomously if it's under the cap, by calling your phone
> if it's over. The agent never holds both sides of that decision."

*Show the kernel decision badge appearing: ESCALATE*

> "That enforcement runs below the agent — in a separate process the agent
> can't touch."

---

## Lie Catch (0:28–0:48) — The differentiator

**Screen:** operator.html — lie-catch demo; type a customer claim, watch the Nemotron verdict

> "The real differentiator: Custodian runs a Nemotron-powered fact-check on
> every justification before the kernel decides. The customer says 'I never
> received it.' Nemotron checks the Stripe record. The claim doesn't match."

*Show the verdict panel: INCONSISTENT — Customer claims non-delivery; Stripe shows delivered and signed.*

> "The kernel gets that verdict before it makes the call. Not a policy check
> in a prompt. A deterministic pipeline."

---

## Real Proof (0:48–1:08) — It's live

**Screen:** switch to Stripe dashboard — show the real PaymentIntent ID on screen

> "Everything you're seeing is real. That's a live Stripe PaymentIntent —
> confirm it yourself at Stripe's API. The SMS approval goes to a real phone.
> The audit log is append-only — the agent can read it, but it can't write to it."

*Show the kill switch: engage, then a spend attempt, then DENIED.*

> "One command kills the agent's authority. Instantly. Across every session."

---

## Tool Layer (1:08–1:18) — Scale

**Screen:** tools.html — the dashboard filters by band, show L0 vs L3 distinction

> "Custodian ships 61 governed tools — HTTP calls, Stripe, NVIDIA NIM inference,
> shell exec — each with an authority band baked in. Add a tool to the registry
> by adding one line to its SKILL.md. The kernel governs everything in the same
> pipeline."

---

## Close (1:18–1:30)

**Screen:** getcustodian.xyz — landing page, live console numbers updating

> "Self-hosted. Rail-agnostic. Swap the model; the enforcement doesn't change.
> getcustodian.xyz — the live console is running right now."

---

## Recording Notes

- Record at 1920×1080, 30fps
- Cursor: large, high-contrast (use Keystroke Pro or similar)
- Real actions only — no cut/paste of fake API responses
- Voiceover: record separately, mix at -3dB
- Export: MP4 H.264, max 200MB for submission upload
- Backup: also export as WebM for the site

## Timestamps to Hit

| Time | Action |
|---|---|
| 0:00 | Open getcustodian.xyz |
| 0:12 | Navigate to /triage |
| 0:28 | Navigate to /operator, open lie-catch panel |
| 0:48 | Open Stripe dashboard in new tab, zoom PI |
| 1:00 | Back to operator — engage kill switch, show denial |
| 1:08 | Navigate to /tools, filter to L3 |
| 1:18 | Navigate to getcustodian.xyz, end on live stats |
