# Custodian — Hackathon Video Script
# Target: 90 seconds. No fluff. Every sentence earns its place.

---

## STRUCTURE OVERVIEW

| Segment | Duration | What's on screen |
|---|---|---|
| Hook | 0:00–0:10 | Black screen → headline |
| Problem | 0:10–0:25 | Split: business owner / developer |
| The solution | 0:25–0:40 | `custodian demo-verify` running live |
| The proof | 0:40–1:05 | `python3 verify_kit.py` running live |
| What it is | 1:05–1:20 | Architecture diagram or landing page |
| Call to action | 1:20–1:30 | `pip install custodian-kernel` |

---

## FULL SCRIPT

---

### [0:00–0:10] HOOK — black screen, white text fades in

> *"Every company deploying an AI agent near money has the same problem."*
> *"The agent can lie. And until now, you had no way to catch it."*

**[Cut to terminal]**

---

### [0:10–0:25] THE PROBLEM — 2 sentences, one for each audience

**[Show the landing page hero at getcustodian.xyz for 3 seconds, then cut to terminal]**

> *"If you're a business owner: your AI agent can approve its own refunds,
> blow your API budget overnight, or pay a vendor without anyone signing off.
> You wouldn't know until after the damage."*

> *"If you're a developer: the only tools available are prompt guardrails and
> API rate limits. Those live inside the agent's own process.
> The agent can route around them."*

---

### [0:25–0:40] THE SOLUTION — run demo-verify live on screen

**[Terminal. Run the command. Let the output speak.]**

```
$ custodian demo-verify
```

**[Wait for output to appear — read it aloud as it prints:]**

> *"Custodian is a kernel-level enforcement layer.
> Not a prompt. Not a policy API. An OS-level boundary
> that runs outside the agent's process.*

> *Watch the claim verifier catch three things in real time:
> a legitimate spend — verified.
> An agent claiming it received money that was never sent — contradicted.
> An agent trying to approve its own refund — contradicted.
> Self-approval is structurally impossible. Not discouraged. Impossible."*

**[Output finishes showing:]**
```
Summary: 1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE
The claim verifier catches lies deterministically.
The agent cannot fool it. This is proven, not claimed.
```

---

### [0:40–1:05] THE PROOF — verify_kit.py running live

**[New terminal window. This is the showstopper moment.]**

> *"But don't take my word for it. This is the part that matters."*

```
$ python3 verify_kit.py
```

**[Read aloud as each phase appears:]**

> *"Phase one — we deliberately reintroduce the original self-approval bug.
> The exact security flaw this was built to prevent.
> The regression test catches it."*

**[Phase 1 result appears:]**
```
Result: REGRESSION TEST CAUGHT IT  ✓
```

> *"Phase two — 1,187 tests. Zero failures."*

```
Result: ALL TESTS PASS (1187 passed, 4 deselected)  ✓
```

> *"Phase three — a real Stripe PaymentIntent, pulled live."*

```
Result: STRIPE CONFIRMED  ✓
```

> *"Phase four — the kill switch. One command stops the agent cold."*

```
Result: KILL SWITCH VERIFIED  ✓
```

**[Final output:]**
```
CUSTODIAN PROVEN
The agent cannot approve its own spend.
```

> *"Every claim on that screen is reproducible.
> Clone the repo. Run that command yourself."*

---

### [1:05–1:20] WHAT IT IS — architecture in one breath

**[Cut to landing page or simple diagram showing: Agent → Custodian Kernel → Stripe]**

> *"Custodian sits between a Nous Hermes agent running on Nemotron
> and real money. Two layers — deliberately separate.*

> *Layer one: the AI. Nous Hermes reads your data, decides what to do,
> and makes a request. It cannot approve its own requests.*

> *Layer two: the kernel. Deterministic. No AI. Checks spend against
> your policy YAML — per-action cap, session budget, authority band.
> Anything over the limit goes to a human's phone via Twilio Verify.
> The agent never sees the approval code.*

> *One policy file. Your rules. The OS enforces them."*

---

### [1:20–1:30] CALL TO ACTION — end on the install command

**[Terminal. Clean. Centered.]**

```
pip install custodian-kernel
custodian demo-verify
```

> *"Custodian. The first kernel that lets you actually deploy AI near money.*
> *pip install custodian-kernel. Prove it yourself."*

**[Fade to: getcustodian.xyz]**

---

## RECORDING NOTES

**What to have open before you hit record:**
1. Terminal 1: ready to type `custodian demo-verify`
2. Terminal 2: ready to type `python3 verify_kit.py`
3. Browser tab: `getcustodian.xyz` loaded and visible

**Font size:** Bump terminal font to 16–18pt so output is readable on video.

**Pacing:** Don't rush the verify_kit output. Let each `✓` land. The pause between phases is the drama.

**The planted-lie moment (0:35):** Slow down here. Say "self-approval is structurally impossible" while ❌ CONTRADICTED is visible. This is the line judges remember.

**The regression test moment (0:45):** This is your differentiator. No other entry can run a command that reintroduces a security bug, proves the test catches it, and restores the fix — live, on camera. Let it breathe.

**Audio:** Voiceover is stronger than on-camera. Record clean audio separately if possible.

**Total runtime:** Script reads at ~85 seconds at a comfortable pace. Don't pad it.

---

## WHAT JUDGES ARE SCORING ON

| Criterion | How this script addresses it |
|---|---|
| **Use of Hermes/Nemotron** | Named explicitly at 1:05 — "Nous Hermes agent running on Nemotron" |
| **Use of NemoClaw** | Can mention at 1:10 — "inside a NemoClaw kernel sandbox" (add if applicable) |
| **Use of Stripe** | Phase 3 of verify_kit.py + real PaymentIntent visible on screen |
| **Usefulness** | 3 concrete business problems solved in 15 seconds (0:10–0:25) |
| **Viability** | `pip install custodian-kernel` — it's already on PyPI, works today |
| **Presentation** | Single command proves the security guarantee on camera. No other entry does this. |

---

## ONE-LINE PITCH (for the Typeform description field)

> "A kernel-enforced authority layer for AI agents: one policy YAML, OS-level spend caps, deterministic claim verification, and a live regression test that proves the self-approval bug can never come back. pip install custodian-kernel."
