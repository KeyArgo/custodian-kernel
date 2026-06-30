# CUSTODIAN — Video Script Rev 4 (90-second cut)
**Length:** ~1:42 (within the 1–3 minute budget)
**Format:** Terminal screen recording + voiceover. No face. No music. Hard cuts only.
**URL:** rein.argobox.com
**Test count:** 1,298

---

## [0:00–0:06] HOOK

**SCREEN:** Terminal, black, cursor blinking.

**VOICEOVER:**
> "The AI tried to approve its own fifty-dollar refund. The kernel said no. Here's what that looks like in code."

---

## [0:06–0:26] `custodian demo verify`

**ACTION:** Type `custodian demo verify` + Enter. Let output print.

**VOICEOVER** (while output scrolls):
> "Four claims. Deterministic verdicts — no AI, no probability.
> Phantom revenue: contradicted. Self-approval: caught.
> Future event: unverifiable. The kernel cannot be hallucinated."

**Hold on the summary line** (`1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE`) for 1 full second.

---

## [0:26–0:48] `custodian demo cycle`

**Pre-check:** `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` must be set.
```bash
export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt
export MODAL_TOKEN_SECRET=$(grep -A3 '\[keyargo\]' ~/.modal.toml | grep token_secret | awk -F'"' '{print $2}')
```
Confirm `custodian demo cycle` shows `GFLOPs:` line (not the fallback string) before pressing record.

**ACTION:** Type `custodian demo cycle` + Enter.

**VOICEOVER** (while steps 1–4 print):
> "Earn. Gate. Spend. Prove. On a real GPU."
> (pause — let the GFLOPs line sit)
> "Both sides match in the ledger. Earn fifty cents, spend a fraction. Every action, deterministic. No human in the loop."

**Hold on** `CYCLE COMPLETE — exit 0` for 1 full second.

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
> (let DENIED print)
> "Every spend denied — even with a valid request. Not a setting. A state."
> (release)
> "Released. Normal evaluation resumes."

**The key moment:** hold on `DENIED — kill switch is engaged` for 1 full second before typing `resume`.

---

## [1:03–1:18] `custodian demo receipt`

**ACTION:** Type `custodian demo receipt` + Enter. Let all 5 steps print.

**VOICEOVER:**
> "Now the decorator. Any Python function, wrapped with @govern — zero kernel code written by the caller."
> (let receipt JSON print)
> "`receipt.verify()` → True. SHA-256 fingerprinted. If the receipt was tampered with, verify fails."
> (let DENIED step print)
> "Kill switch engaged: function body never ran."

---

## [1:18–1:27] TEST PROOF

**ACTION:** Type `python3 -m pytest tests/ --tb=no -q` + Enter.

**VOICEOVER** (while progress bar runs):
> "Twelve ninety-eight tests. Zero failures."

**Hold on** `1298 passed` line for 1.5 seconds.

---

## [1:27–1:45] CLOSE — 3 CARDS ON BLACK

**Slide 1** [1:27–1:32]:
```
CUSTODIAN
THE AGENT CANNOT APPROVE ITS OWN SPEND.
THE KERNEL ENFORCES IT — IN CODE, NOT IN A PROMPT.
```

**Slide 2** [1:32–1:38]:
```
pip install custodian-kernel
custodian demo receipt
```

**Slide 3** [1:38–1:45]:
```
REIN.ARGOBOX.COM
```

No voiceover on any slide. Silence. Hard cuts.

---

## CHANGES FROM REV 3

| What changed | Why |
|---|---|
| Opening hook now leads with the contradiction caught, not the problem statement | External review: "judges decide in 6 seconds" — lead with the lie caught |
| Kill switch added back (15 seconds) | Was cut from Rev 3; it's the single thing no other entry has proven |
| Close is "in code, not in a prompt" instead of "pip install" | Stronger final impression; install command moves to Slide 2 |
| `custodian demo receipt` kept (13 seconds) | External review incorrectly claimed it didn't exist — it ships in 0.2.0 and runs clean |
| Test count: 1,298 (not 1,245 or 1,278) | 0.2.0 added 53 tests; 1,278 from external review was wrong |
| URL: rein.argobox.com (not getcustodian.xyz) | External review hallucinated a domain |

---

## PRE-RECORD CHECKLIST

- [ ] `custodian demo verify` runs and shows `1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE`
- [ ] `export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt` + `MODAL_TOKEN_SECRET` from `~/.modal.toml [keyargo]`
- [ ] `custodian demo cycle` dry-run shows `GFLOPs:` line (real GPU), NOT the fallback string
- [ ] `custodian demo receipt` dry-run shows `receipt.verify() → True` and `verdict: DENIED` on step 5
- [ ] `python3 -m pytest tests/ --tb=no -q` returns `1298 passed`
- [ ] Terminal font ≥ 18pt, 1920×1080
- [ ] Kill switch released before recording: `custodian resume --by operator` (or delete `~/.custodian/kill_switch.json`)
