# Custodian — Video Script (90 seconds to #1)

**One-sentence hook:** "We planted a lie in the customer data. The AI believed it. The kernel didn't."

**Target:** 90 seconds | **Format:** screen recording + voiceover | **Tone:** calm, precise — let the proof do the talking

---

## HOOK (0:00–0:08) — The lie

**Screen:** Terminal. Run the planted-lie demo:
```bash
python3 verify_kit.py
```
Let it print — pause on the `[CONTRADICTED]` line in red.

> "We planted a lie. Customer said the package never arrived.
> Nemotron believed her — 89% confidence, approve.
> The verifier checked Stripe. Delivered. Signed.
> The kernel blocked it. No prompt engineering. Structurally impossible to override."

---

## THE PROOF (0:08–0:28) — verify_kit live

**Screen:** Continue watching verify_kit.py output scroll:
- `[PASS] 1,176 passed`
- `[PASS] Lie-catcher catches the planted lie`
- `[PASS] Self-approval regression catches the bug`
- `[PASS] Live public dashboard data is real`

> "One command. Four independent checks.
> The test suite runs. The lie gets caught. The security bug gets proven
> by reintroducing it live — watch the test fail — then restoring the fix.
> The live dashboard pulls real data from getcustodian.xyz right now.
> Run it yourself. That's not a slide."

---

## EARN → BUY LOOP (0:28–0:52) — the closed economic cycle

**Screen:** Browser, getcustodian.xyz/operator
P&L bar shows: EARNED $0 · SPENT $0 · NET $0

Click **"⚡ Simulate Payment Received"** — EARNED flips to **+$25.00**

Navigate to /triage, Cloud pack — click case **01: Modal A10G auto-provision**
Verdict panel loads: `AUTONOMOUS · L2 · cost VERIFIED · provider APPROVED`
Panel shows: `execution: { provider: "nvidia-nim", response: "Job provisioned", billed: $1.20 }`

Return to /operator — P&L: EARNED $25.00 · SPENT $1.20 · NET **+$23.80** · MARGIN **95%**

> "Customer pays $25. Agent needs compute to fulfill the job.
> Claims verified: cost matches catalog, provider approved, under the $5 cap.
> Kernel says AUTONOMOUS. NIM spins up. Spend logged.
> Earned, spent, net — every step in the audit trail.
> The agent never touched the accounting. The kernel did."

---

## KILL SWITCH (0:52–1:05) — the safety primitive

**Screen:** Operator panel → engage kill switch.
Switch to /triage → run any case → badge reads: **DENIED · Kill switch active**
Release kill switch → same case → **AUTONOMOUS**

**While kill switch is active, hold phone to camera — SMS arriving in real time**

> "One toggle. All agent authority revoked instantly.
> The real text message goes to a real phone — not a demo phone, a real number.
> The kernel is below the prompt layer. You can't social-engineer around it."

---

## SCALE (1:05–1:18) — 3 domains, same kernel

**Screen:** Fast cuts — Refunds pack: fraud caught. Purchasing pack: inflated invoice caught. Cloud pack: unapproved provider blocked.

> "Three business domains. Same kernel.
> Refunds, purchasing, cloud provisioning — one enforcement layer.
> 53 live tools ship with it. Add one with a YAML line.
> MSPs, SaaS platforms, anyone running agents with real authority."

---

## CLOSE (1:18–1:30)

**Screen:** getcustodian.xyz

> "getcustodian.xyz — live right now.
> Run verify_kit.py — one command, verify everything yourself.
> Built on Hermes, NVIDIA Nemotron, Stripe, Modal.
> This is what agent authority looks like when you actually enforce it."

---

## Why This Script Beats #2

| What HermesCo shows | What Custodian shows |
|---|---|
| Agent approves a job (positive path) | Agent blocked by kernel (failure = safety proof) |
| Nemotron logo on screen | Real NIM inference call in the audit log |
| "Trust our dashboard" | `verify_kit.py` — run it yourself |
| 1 business domain | 3 domains, same kernel |
| No tests shown | 1,176 tests running live on camera |
| Built with Devin | You can read every line |

The differentiator isn't what Custodian approves — it's what it **stops**.
The verify_kit is what no other entry has. Lead with it.

---

## Recording Notes

- Record at 1920×1080, 30fps. Terminal font size 18+ for readability.
- Cursor: large, high-contrast
- Real actions only — no staged API responses
- Voiceover: record separately, mix at -3dB under screen audio
- Keep verify_kit output visible for 10+ seconds — let judges read it
- Export: MP4 H.264, ≤200MB

## Pre-Recording Checklist

- [ ] `pip install -e ".[dev]"` completed, all tests pass (`pytest` clean)
- [ ] `NVIDIA_API_KEY` exported from `secrets/keys.env`
- [ ] `python3 verify_kit.py` does a clean full run first (dry run)
- [ ] Flask dashboard running: `flask --app dashboard.app run --port 5050`
- [ ] Earn ledger cleared (fresh start)
- [ ] Browser at 110% zoom, getcustodian.xyz open
- [ ] Stripe dashboard open in a separate tab (for PaymentIntent verification)
- [ ] Kill switch confirmed OFF in operator panel
- [ ] Real Twilio number configured — test SMS works before recording
- [ ] One full dry run end-to-end before hitting record

## Timestamps

| Time | Screen | Audio |
|------|--------|-------|
| 0:00 | Terminal: `python3 verify_kit.py` starts | "We planted a lie..." |
| 0:06 | `[CONTRADICTED]` in red | "The kernel blocked it." |
| 0:08 | Tests running: 1,176 passed | "One command. Four checks." |
| 0:20 | Live dashboard pull succeeds | "Run it yourself. That's not a slide." |
| 0:28 | /operator P&L at $0 | "Customer pays $25..." |
| 0:31 | Click ⚡ — EARNED flips to $25 | |
| 0:34 | /triage cloud pack, case 01 | "Agent needs compute..." |
| 0:42 | Panel: AUTONOMOUS + execution: nvidia-nim | "Kernel says AUTONOMOUS. NIM spins up." |
| 0:48 | /operator P&L: NET +$23.80, MARGIN 95% | "Earned, spent, net." |
| 0:52 | Engage kill switch | "One toggle." |
| 0:57 | Case run → DENIED · Kill switch active | |
| 1:00 | Hold phone to camera (SMS arriving) | "Real text. Real phone." |
| 1:03 | Release kill switch → AUTONOMOUS | |
| 1:05 | Fast cuts: fraud / inflated invoice / unapproved provider all blocked | "Three domains. Same kernel." |
| 1:18 | getcustodian.xyz landing | "Run verify_kit.py." |
| 1:27 | Fade on live audit feed | |
