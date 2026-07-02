# CUSTODIAN — Video Script Rev 5 (90-second cut)

**Length:** ~1:42
**Format:** Terminal screen recording + voiceover. No face. No music. Hard cuts only.
**URL:** getcustodian.xyz
**Test count:** 1,346

---

## [0:00–0:06] HOOK

**SCREEN:** Terminal, black, cursor blinking.

**VOICEOVER:**
> "The AI tried to approve its own fifty-dollar refund. The kernel said no."

---

## [0:06–0:26] custodian demo verify

**ACTION:** Type `custodian demo verify` + Enter. Let output print.

**VOICEOVER** (while output scrolls):
> "Four claims. Deterministic verdicts, no AI, no probability. Phantom revenue, contradicted. Self-approval, caught. Future event, unverifiable. The kernel can't be hallucinated."

Hold on the summary line (1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE) for 1 second.

---

## [0:26–0:48] custodian demo cycle

**Pre-check:** MODAL_TOKEN_ID and MODAL_TOKEN_SECRET must be set.

```bash
export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt
export MODAL_TOKEN_SECRET=$(grep -A3 '\[keyargo\]' ~/.modal.toml | grep token_secret | awk -F'"' '{print $2}')
```

Confirm `custodian demo cycle` shows `GFLOPs:` line (real GPU), NOT the fallback string, before pressing record.

**ACTION:** Type `custodian demo cycle` + Enter.

**VOICEOVER** (while steps 1–4 print):
> "Earn. Gate. Spend. Prove. On a real GPU."
>
> *(pause)*
>
> "Both sides match. Fifty cents in, a fraction out. Every action, deterministic. No human in the loop."

Hold on `CYCLE COMPLETE — exit 0` for 1 second.

---

## [0:48–1:03] KILL SWITCH

**ACTION — 3 commands in sequence:**

```bash
custodian kill --by operator
custodian request --amount 40.00 --description "cloud backup"
custodian resume --by operator
```

**VOICEOVER:**
> "Kill switch engaged."
>
> *(pause)*
>
> "Every spend denied, all of them. Not a setting. A state."
>
> *(pause)*
>
> "Released. Normal evaluation resumes."

The key moment: hold on `DENIED — kill switch is engaged` for 1 second before typing resume.

---

## [1:03–1:18] custodian demo receipt

**ACTION:** Type `custodian demo receipt` + Enter. Let all 5 steps print.

**VOICEOVER:**
> "Any function. Wrapped with at govern. The caller doesn't write a single line of kernel code."
>
> *(pause)*
>
> "Receipt dot verify, returns true. SHA two fifty-six fingerprinted. Change one byte, verification fails."
>
> *(pause)*
>
> "Kill switch engaged, function body never ran."

---

## [1:18–1:27] TEST PROOF

**ACTION:** Type `python3 -m pytest tests/ --tb=no -q` + Enter.

**VOICEOVER** (while progress bar runs):
> "Thirteen forty-six tests. Zero failures."

Hold on `1346 passed` line for 1.5 seconds.

---

## [1:27–1:45] CLOSE — 3 CARDS ON BLACK

**Slide 1 [1:27–1:32]:**

```
CUSTODIAN
THE AGENT CANNOT APPROVE ITS OWN SPEND.
THE KERNEL ENFORCES IT — IN CODE, NOT IN A PROMPT.
```

**Slide 2 [1:32–1:38]:**

```
pip install custodian-kernel
custodian demo receipt
```

**Slide 3 [1:38–1:45]:**

```
GETCUSTODIAN.XYZ
```

No voiceover on any slide. Silence. Hard cuts.

---

## CHANGES FROM REV 4

- Hook cut from 3 lines to 2
- Voiceover rewritten for natural rhythm (shorter sentences, fewer abstractions)
- "Twelve ninety-eight" → "Thirteen forty-six" (test count updated: 1,346 passing)
- "Receipt.verify() → True" → "Receipt dot verify, returns true" (matches how you'd say it)
- Receipt line: "Zero kernel code written by the caller" → "The caller doesn't write a single line of kernel code"
- "SHA-256 fingerprinted. If the receipt was tampered with, verify fails" → "SHA two fifty-six fingerprinted. Change one byte, verification fails"
- Modal token secret command corrected (was garbled in Rev 4)

---

## PRE-RECORD CHECKLIST

- [ ] `custodian demo verify` runs and shows `1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE`
- [ ] `export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt` + `MODAL_TOKEN_SECRET` from `~/.modal.toml [keyargo]`
- [ ] `custodian demo cycle` dry-run shows `GFLOPs:` line (real GPU), NOT the fallback string
- [ ] `custodian demo receipt` dry-run shows `receipt.verify() → True` and `verdict: DENIED` on step 5
- [ ] `python3 -m pytest tests/ --tb=no -q` returns `1346 passed`
- [ ] Terminal font ≥ 18pt, 1920×1080
- [ ] Kill switch released before recording: `custodian resume --by operator` (or delete `~/.custodian/kill_switch.json`)

---

## WHAT YOU SAY (print this, ignore everything else)

> "The AI tried to approve its own fifty-dollar refund. The kernel said no."

> "Four claims. Deterministic verdicts, no AI, no probability. Phantom revenue, contradicted. Self-approval, caught. Future event, unverifiable. The kernel can't be hallucinated."

> "Earn. Gate. Spend. Prove. On a real GPU."

> "Both sides match. Fifty cents in, a fraction out. Every action, deterministic. No human in the loop."

> "Kill switch engaged."

> "Every spend denied, all of them. Not a setting. A state."

> "Released. Normal evaluation resumes."

> "Any function. Wrapped with at govern. The caller doesn't write a single line of kernel code."

> "Receipt dot verify, returns true. SHA two fifty-six fingerprinted. Change one byte, verification fails."

> "Kill switch engaged, function body never ran."

> "Thirteen forty-six tests. Zero failures."

---

*Total voiceover: ~120 words, ~22 seconds at 150 wpm. The other 80 seconds is the demo running and the silent close slides.*
