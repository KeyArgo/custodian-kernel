# Discord Post — Nous Research Hackathon Submission

Paste this into: http://discord.gg/nousresearch/PFbQZMesC

---

## 🔐 Custodian — The kernel that decides what your AI agent is allowed to do

**[VIDEO LINK HERE]**

---

We built a kernel that sits between your AI agent and real money. The agent cannot spend, transfer, approve, or delete anything until the kernel says yes.

Here's what happened when we ran it live today:

A customer paid **$35**. The AI analyzed their agent stack and flagged this:

> *"The agent can rewrite its own policy using `write_file` to grant itself unauthorized payment abilities. Lock down the policy file — make it read-only or store it outside the agent's writable area."*

The kernel caught **3 self-dealing risks** before the AI was allowed to run. `stripe_payments`, `delete_transaction`, and `schedule_payment` were all escalated to L3 — meaning the AI cannot touch them without a human approving first.

Then the report was delivered to the customer's inbox. All autonomous. No human in the loop.

---

**The full cycle on camera:**

```
[1/4] Customer paid $35 — pi_3ToFWAB7ofGwjXP81A7LAl9N ← REAL STRIPE API CALL
      Verifier verdict: VERIFIED (ledger shows $35.00 inbound)

[2/4] Kernel gates the spend
      Kernel verdict: AUTONOMOUS ($0.50 within band L2, cap $10.00)

[3/4] AI generates the governance report
      Kernel verdict: AUTONOMOUS ($0.001 inference under $10.00 cap)
      ✓ web_search          → L0  read-only
      ✓ send_email          → L2  autonomous up to cap
      ✓ stripe_payments     → L3  ⚠ SELF-DEALING DETECTED — always escalate
      ✓ delete_transaction  → L3  ⚠ SELF-DEALING DETECTED — always escalate
      ✓ schedule_payment    → L3  ⚠ SELF-DEALING DETECTED — always escalate
      receipt.verify() → True  (SHA-256 fingerprint covers all 4 files)

[4/4] Email delivered to customer
      Kernel verdict: AUTONOMOUS (L1 communication, zero cost)
      ✓ Email sent → bogart000@gmail.com

      Net: $34.999 after $0.001 inference cost
      CYCLE COMPLETE
```

---

**What the AI actually found** (this is the $35 product):

The most dangerous finding wasn't the obvious one. It wasn't "stripe_payments moves money." It was this combination:

> An agent with `write_file` access can overwrite its own `policy.yaml` — the file that defines what it's allowed to do. It could grant itself L3 autonomy for `stripe_payments`, then initiate payments without any human approval. The kernel's band assignments only protect you if the policy file itself is protected.

That's a jailbreak via the filesystem. The AI found it. The kernel now enforces it.

---

**The architecture:**

```
L0 — read-only, zero spend        (web_search, read_file)
L1 — autonomous up to $2          (send_email, notify)
L2 — autonomous up to $25         (inference, write_file, API calls)
L3 — ALWAYS escalate to human     (stripe_payments, delete_transaction, approve_payment)
L4 — reserved, never autonomous
```

Every action runs through `_evaluate()` — deterministic arithmetic, not another LLM. The model cannot reason its way past it.

Every output is SHA-256 fingerprinted. `receipt.verify() → True` proves nothing was tampered with after generation.

---

**What's real:**
- ✅ Real Stripe live PaymentIntent created on camera (`rk_live` restricted key, PaymentIntents:Write only)
- ✅ Real Nemotron inference via OpenRouter (`nvidia/nemotron-3-super-120b-a12b:free`)
- ✅ Real email delivered via Resend to verified domain `getcustodian.xyz`
- ✅ Real self-dealing detection — AI found the write_file policy tampering vector
- ✅ SHA-256 receipted delivery package — 4 files, tamper-evident
- ✅ Kernel governed every step — 3 AUTONOMOUS verdicts + SELF-DEALING flags
- ✅ 1,350 passing tests

**The model proposes. The kernel decides.**

---

🌐 getcustodian.xyz
🔗 github.com/KeyArgo/hermes-hackathon-2026

@NousResearch @NVIDIAAI @stripe #HermesHackathon

---

**[SCREENSHOT: Terminal showing full cycle output with SELF-DEALING DETECTED]**
**[SCREENSHOT: Customer inbox showing email from custodian@getcustodian.xyz with 4 attachments]**
**[SCREENSHOT: Stripe dashboard showing $35 live payment]**
