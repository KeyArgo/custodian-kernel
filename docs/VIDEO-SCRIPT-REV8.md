# CUSTODIAN — Video Script Rev 8 (90-second cut)

**Length:** ~1:45
**Format:** Terminal screen recording + voiceover. No face. No music. Hard cuts only.
**URL:** getcustodian.xyz
**Test count:** 1,350

---

## HOW TO RECORD

### Terminal setup
- Font: Monospace 18pt or larger
- Resolution: 1920×1080 fullscreen
- Dark background, high-contrast text
- `clear` before pressing record

### Credentials — set before recording
```bash
export STRIPE_SECRET_KEY=sk_test_YOUR_KEY_HERE   # or sk_live_... for real charge
export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt
export MODAL_TOKEN_SECRET=$(grep -A3 '\[keyargo\]' ~/.modal.toml | grep token_secret | awk -F'"' '{print $2}')
```

### Workspace directory
Kill switch commands default to `./state` — must be in the directory containing `state/custodian.db`:
```bash
cd /path/to/your/custodian-workspace
```

### Kill switch — clear before recording
```bash
custodian resume --by operator 2>/dev/null; true
```

---

## [0:00–0:06] HOOK

**SCREEN:** Terminal, black, cursor blinking.

**VOICEOVER:**
> "The AI tried to approve its own fifty-dollar refund. The kernel said no."

---

## [0:06–0:24] custodian demo verify

**ACTION:** Type `custodian demo verify` + Enter. Let output print.

**VOICEOVER** (while output scrolls):
> "Four claims. Deterministic verdicts, no AI, no probability. Phantom revenue, contradicted. Self-approval, caught. Future event, unverifiable. The kernel can't be hallucinated."

Hold on this line for **1 second**:
```
Summary: 1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE
```

---

## [0:24–1:00] THE SALE — custodian demo cycle

The centerpiece. Dad pays $35 for a month of inference. The kernel governs every cent that leaves.

**ACTION:** Type `custodian demo cycle` + Enter. Let all 4 steps print.

**VOICEOVER:**

*(while [1/4] EARNING prints)*
> "Customer pays thirty-five dollars. Real Stripe payment. Verified."

Hold on this block for **2 seconds**:
```
  Amount:         $35.00 inbound
  ...
  Verifier verdict:  VERIFIED  (ledger shows $35.00 inbound)
```

*(while [2/4] KERNEL GATES prints)*
> "The kernel gates every outbound spend. Autonomous. Under cap. No human needed."

*(while [3/4] THE SPEND prints)*
> "Real GPU. Real inference. Fraction of a cent."

Hold on this line for **1 second**:
```
  Elapsed: 9.4s | GFLOPs: 214.0 | Billed: $0.002131
```

*(while [4/4] CYCLE CLOSED prints)*
> "Thirty-five dollars in. A fraction out. The margin is real."

Hold on this block for **3 seconds** — longest hold in the video:
```
  Inbound:   $35.00
  Outbound:  $0.002131  (Modal GPU)
  Net:       $34.997869
```

Then hold on `CYCLE COMPLETE — exit 0` for **1 second**.

---

## [1:00–1:12] KILL SWITCH

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
> "Every spend denied. Not a setting. A state."
>
> *(pause)*
>
> "Released. Normal evaluation resumes."

Hold on this line for **1 second** before typing `resume`:
```
DENIED: kill switch is engaged (by operator).
```

---

## [1:12–1:24] custodian demo receipt

**ACTION:** Type `custodian demo receipt` + Enter.

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

## [1:24–1:32] TEST PROOF

**ACTION:** Type `python3 -m pytest tests/ --tb=no -q` + Enter.

**VOICEOVER** (while dots scroll):
> "Every property the kernel claims — tested."

On the final line:
> "Thirteen fifty. Zero failures."

Hold on this line for **1.5 seconds**:
```
1350 passed, 4 deselected in 16.33s
```

---

## [1:32–1:48] CLOSE — 3 CARDS ON BLACK

**Slide 1 [1:32–1:37]:**
```
CUSTODIAN
THE AGENT CANNOT APPROVE ITS OWN SPEND.
THE KERNEL ENFORCES IT — IN CODE, NOT IN A PROMPT.
```

**Slide 2 [1:37–1:43]:**
```
pip install custodian-kernel
custodian demo receipt
```

**Slide 3 [1:43–1:48]:**
```
GETCUSTODIAN.XYZ
```

No voiceover. Silence. Hard cuts.

---

## PRE-RECORD CHECKLIST

- [ ] `export STRIPE_SECRET_KEY=sk_test_...` (or `sk_live_...` for real charge to dad's card)
- [ ] `export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt`
- [ ] `export MODAL_TOKEN_SECRET=$(grep -A3 '\[keyargo\]' ~/.modal.toml | grep token_secret | awk -F'"' '{print $2}')`
- [ ] `cd` into workspace directory containing `state/custodian.db`
- [ ] `custodian demo cycle` dry-run shows `$35.00 inbound` AND `GFLOPs:` without fallback string
- [ ] `custodian demo verify` shows `1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE`
- [ ] `custodian demo receipt` shows `receipt.verify() → True` and `verdict : DENIED` on step 5
- [ ] `python3 -m pytest tests/ --tb=no -q` returns `1350 passed, 4 deselected`
- [ ] Kill switch cleared: `custodian resume --by operator 2>/dev/null; true`
- [ ] Terminal font ≥ 18pt, 1920×1080, dark theme
- [ ] `clear` before pressing record

---

## WHAT YOU SAY (print this, ignore everything else)

> "The AI tried to approve its own fifty-dollar refund. The kernel said no."

> "Four claims. Deterministic verdicts, no AI, no probability. Phantom revenue, contradicted. Self-approval, caught. Future event, unverifiable. The kernel can't be hallucinated."

> "Customer pays thirty-five dollars. Real Stripe payment. Verified."

> "The kernel gates every outbound spend. Autonomous. Under cap. No human needed."

> "Real GPU. Real inference. Fraction of a cent."

> "Thirty-five dollars in. A fraction out. The margin is real."

> "Kill switch engaged."

> "Every spend denied. Not a setting. A state."

> "Released. Normal evaluation resumes."

> "Any function. Wrapped with at govern. The caller doesn't write a single line of kernel code."

> "Receipt dot verify, returns true. SHA two fifty-six fingerprinted. Change one byte, verification fails."

> "Kill switch engaged, function body never ran."

> "Every property the kernel claims — tested."

> "Thirteen fifty. Zero failures."

---

## CHANGES FROM REV 7

- Earn amount changed $0.50 → **$35.00** (one line changed in `cmd_earn_and_buy.py`)
- Demo cycle is now the centerpiece — expanded, 3-second hold on Net line
- Voiceover rewritten for cycle: real payment, margin, GPU spend
- Kill switch section trimmed to compensate
- Net line `$34.997869` is the longest hold — silence is stronger than voiceover there

---

*Total voiceover: ~140 words. The Net line hold is the emotional peak — $34.997869 on screen in silence.*
