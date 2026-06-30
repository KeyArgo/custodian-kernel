# CUSTODIAN — Video Script Rev 4 (Human Read Version)
**Read this one aloud. Rev4-90s.md is the technical reference.**
**Don't perform it — just talk. The imperfections are intentional.**

---

## [0:00–0:06] HOOK

*(terminal on screen, cursor blinking, you start talking before you type)*

> "So — the AI tried to approve its own fifty-dollar refund."
> *(beat)*
> "The kernel said no. Let me show you what that actually looks like."

---

## [0:06–0:26] `custodian demo verify`

*(type the command, let it run, talk while it prints)*

> "This is the claim verifier. Four claims come in —"
> *(watch the first verdict print)*
> "— and it just... decides. No AI, no probability, no guessing."
> *(self-approval verdict prints)*
> "There it is. Agent tried to approve its own refund. Contradicted."
> *(let the summary line sit for a second)*
> "You can't hallucinate your way past this."

---

## [0:26–0:48] `custodian demo cycle`

*(type the command)*

> "Now a real GPU job."
> *(step 1 prints — earning)*
> "Earn fifty cents —"
> *(step 2 prints — kernel gates)*
> "— kernel checks it —"
> *(step 3 prints — GFLOPs line appears)*
> "— and there's the actual compute. Real gigaflops, real bill."
> *(let CYCLE COMPLETE sit)*
> "Both sides match in the ledger. The agent can't fake either number."

---

## [0:48–1:03] KILL SWITCH

*(type `custodian kill --by operator` — pause after it fires)*

> "Kill switch."
> *(type the request command)*
> "Forty dollars. Totally valid request."
> *(DENIED prints)*
> "Denied. Doesn't matter what the policy says — the switch is on."
> *(type `custodian resume --by operator`)*
> "And... released. That's it. Not a setting you configure. A state the kernel holds."

---

## [1:03–1:18] `custodian demo receipt`

*(type the command)*

> "This is new in 0.2.0. You put `@govern` on any Python function —"
> *(step 2 prints — AUTONOMOUS verdict)*
> "— the kernel intercepts the call. The caller doesn't know Custodian exists."
> *(receipt JSON prints)*
> "Every execution gets a receipt. SHA-256 fingerprinted."
> *(step 4 prints — `receipt.verify() → True`)*
> "Tamper with it, verify fails."
> *(step 5 prints — DENIED)*
> "Kill switch back on — function body never ran."

---

## [1:18–1:27] TEST PROOF

*(type `python3 -m pytest tests/ --tb=no -q`)*

*(say nothing — let the progress bar run)*

*(when `1298 passed` prints)*
> "Twelve ninety-eight. Zero failures."

*(hold on it for a beat, then cut)*

---

## [1:27–1:45] CLOSE — 3 CARDS, NO VOICEOVER

*(pure silence — let the cards speak)*

```
CUSTODIAN
THE AGENT CANNOT APPROVE ITS OWN SPEND.
THE KERNEL ENFORCES IT — IN CODE, NOT IN A PROMPT.
```

```
pip install custodian-kernel
custodian demo receipt
```

```
REIN.ARGOBOX.COM
```

---

## NOTES FOR READING THIS

**The dashes mean pause.** "Earn fifty cents —" means let the output catch up before you continue.

**Don't rush the kills.** After `DENIED` prints, stay silent for a full second. That silence does more than any word.

**"And... released."** The ellipsis is real — a small breath there sounds like confidence, not hesitation.

**The test count.** Don't say "one thousand two hundred and ninety-eight." Say "twelve ninety-eight." It's how engineers talk about test counts.

**If you stumble** on a word, don't stop — keep going. A small stumble reads as human. Stopping and restarting reads as scripted.

**You don't need to sound excited.** Flat and certain beats enthusiastic. The output is exciting enough.
