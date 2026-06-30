# CUSTODIAN — Video Script Rev 6

**Length:** ~1:45
**Format:** Terminal screen recording + voiceover. No face. No music. Hard cuts only.
**URL:** getcustodian.xyz
**Test count:** 1,347

---

## HOW TO RECORD — READ THIS FIRST

### 1. Install a screen recorder

**Linux (recommended):**
```bash
# OBS Studio — free, outputs MP4
sudo zypper install obs-studio   # or: flatpak install flathub com.obsproject.Studio
```

**Quick alternative (no install):**
```bash
# ffmpeg screen capture (built into most distros)
ffmpeg -video_size 1920x1080 -framerate 30 -f x11grab -i :0.0 \
       -c:v libx264 -preset ultrafast custodian-demo.mp4
# Press q to stop recording
```

### 2. Set up your terminal

- **Font:** Monospace 18pt or larger (JetBrains Mono, Fira Code, or any mono)
- **Resolution:** 1920×1080 fullscreen
- **Theme:** Dark background, high-contrast text (black terminal, white text is fine)
- **Window:** Fullscreen — no taskbar, no title bar if possible
- **Clear history:** `clear` before each section so old output isn't visible

### 3. Set credentials before you start

Open a fresh terminal and run these ONCE before pressing record:

```bash
export STRIPE_SECRET_KEY=sk_test_YOUR_KEY_HERE
export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt
export MODAL_TOKEN_SECRET=$(grep -A3 '\[keyargo\]' ~/.modal.toml | grep token_secret | awk -F'"' '{print $2}')
```

**Verify they work — dry-run before recording:**
```bash
custodian demo cycle     # must show GFLOPs: line AND ← REAL STRIPE API CALL
custodian demo receipt   # must show receipt.verify() → True and DENIED on step 5
custodian demo verify    # must show 1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE
python3 -m pytest tests/ --tb=no -q   # must show 1347 passed
```

If `demo cycle` shows `test (simulated — set STRIPE_SECRET_KEY=sk_test_... for live)` instead of `← REAL STRIPE API CALL`, your Stripe key is missing or wrong.

If `demo cycle` shows fallback GFLOPs numbers, Modal creds are missing.

**Do not record until all four dry-runs pass.**

### 4. Kill switch state — clear it before recording

```bash
custodian resume --by operator 2>/dev/null; true
```

Or: `rm -f ~/.custodian/kill_switch.json`

### 5. Recording flow

- Start OBS/ffmpeg recording
- Type each command as shown below — **don't copy-paste on camera**, type it
- Pause 1–2 seconds after each command's output finishes before moving on
- You can do multiple takes and cut — the script below is one continuous take

---

## [0:00–0:06] HOOK

**SCREEN:** Terminal, black, cursor blinking. Just the prompt. Nothing else.

**VOICEOVER:**
> "The AI tried to approve its own fifty-dollar refund. The kernel said no."

---

## [0:06–0:26] custodian demo verify

**ACTION:** Type exactly:
```
custodian demo verify
```
Press Enter. Let output print to completion.

**VOICEOVER** (while output scrolls):
> "Four claims. Deterministic verdicts, no AI, no probability. Phantom revenue, contradicted. Self-approval, caught. Future event, unverifiable. The kernel can't be hallucinated."

**Hold** on the summary line `1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE` for **1 second** before moving on.

---

## [0:26–0:48] custodian demo cycle

**Pre-check (done before recording — not on camera):**
Credentials must be set in the same terminal session. See HOW TO RECORD above.

**ACTION:** Type exactly:
```
custodian demo cycle
```
Press Enter. Let all 4 steps print.

**VOICEOVER** (while steps 1–4 print):
> "Earn. Gate. Spend. Prove. On a real GPU."
>
> *(pause — let the Stripe PI line appear)*
>
> "A real Stripe payment. The kernel gates it. A real GPU job proves the spend."
>
> *(pause)*
>
> "Both sides verified. Fifty cents in, a fraction out. Deterministic, end to end."

**Hold** on `CYCLE COMPLETE — exit 0` for **1 second**.

---

## [0:48–1:03] KILL SWITCH

**ACTION — type 3 commands in sequence:**

```
custodian kill --by operator
```
*(let output print — shows KILL SWITCH ENGAGED)*

```
custodian request --amount 40.00 --description "cloud backup"
```
*(let output print — shows DENIED: kill switch is engaged)*

```
custodian resume --by operator
```
*(let output print — shows Kill switch released)*

**VOICEOVER:**
> "Kill switch engaged."
>
> *(pause — let the DENIED line appear)*
>
> "Every spend denied, all of them. Not a setting. A state."
>
> *(pause)*
>
> "Released. Normal evaluation resumes."

**Key moment:** Hold on `DENIED — kill switch is engaged` for **1 second** before typing `resume`.

---

## [1:03–1:18] custodian demo receipt

**ACTION:** Type exactly:
```
custodian demo receipt
```
Press Enter. Let all 5 steps print.

**VOICEOVER:**
> "Any function. Wrapped with at govern. The caller doesn't write a single line of kernel code."
>
> *(pause — let receipt JSON appear)*
>
> "Receipt dot verify, returns true. SHA two fifty-six fingerprinted. Change one byte, verification fails."
>
> *(pause — let DENIED appear on step 5)*
>
> "Kill switch engaged, function body never ran."

---

## [1:18–1:27] TEST PROOF

**ACTION:** Type exactly:
```
python3 -m pytest tests/ --tb=no -q
```
Press Enter. Let the progress bar run.

**VOICEOVER** (while progress bar runs):
> "Thirteen forty-seven tests. Zero failures."

**Hold** on `1347 passed` line for **1.5 seconds**.

---

## [1:27–1:45] CLOSE — 3 CARDS ON BLACK

Stop the terminal recording here. Switch to 3 full-screen black slides with white text. Hard cuts between each.

**Slide 1 [1:27–1:32] — 5 seconds:**
```
CUSTODIAN
THE AGENT CANNOT APPROVE ITS OWN SPEND.
THE KERNEL ENFORCES IT — IN CODE, NOT IN A PROMPT.
```

**Slide 2 [1:32–1:38] — 6 seconds:**
```
pip install custodian-kernel
custodian demo receipt
```

**Slide 3 [1:38–1:45] — 7 seconds:**
```
GETCUSTODIAN.XYZ
```

No voiceover on any slide. Silence. Hard cuts.

**How to make the slides:**
- Simplest: open a text editor fullscreen with black background, white text, centered
- Or: `xdotool` / `feh` / a quick HTML file opened in a browser fullscreen
- Or: record them as separate terminal `echo` commands with `clear` first

---

## PRE-RECORD CHECKLIST

- [ ] `export STRIPE_SECRET_KEY=sk_test_...` — your Stripe test key
- [ ] `export MODAL_TOKEN_ID=ak-EqGfd6yhEfLRozgQoO7Rgt`
- [ ] `export MODAL_TOKEN_SECRET=$(grep -A3 '\[keyargo\]' ~/.modal.toml | grep token_secret | awk -F'"' '{print $2}')`
- [ ] `custodian demo verify` shows `1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE`
- [ ] `custodian demo cycle` shows `← REAL STRIPE API CALL` AND `GFLOPs:` (not fallback)
- [ ] `custodian demo receipt` shows `receipt.verify() → True` and `verdict: DENIED` on step 5
- [ ] `python3 -m pytest tests/ --tb=no -q` returns `1347 passed`
- [ ] Terminal font ≥ 18pt, 1920×1080, dark theme
- [ ] Kill switch cleared: `custodian resume --by operator 2>/dev/null; true`
- [ ] `clear` the terminal before starting recording

---

## WHAT YOU SAY (print this page, ignore everything else)

> "The AI tried to approve its own fifty-dollar refund. The kernel said no."

> "Four claims. Deterministic verdicts, no AI, no probability. Phantom revenue, contradicted. Self-approval, caught. Future event, unverifiable. The kernel can't be hallucinated."

> "Earn. Gate. Spend. Prove. On a real GPU."

> "A real Stripe payment. The kernel gates it. A real GPU job proves the spend."

> "Both sides verified. Fifty cents in, a fraction out. Deterministic, end to end."

> "Kill switch engaged."

> "Every spend denied, all of them. Not a setting. A state."

> "Released. Normal evaluation resumes."

> "Any function. Wrapped with at govern. The caller doesn't write a single line of kernel code."

> "Receipt dot verify, returns true. SHA two fifty-six fingerprinted. Change one byte, verification fails."

> "Kill switch engaged, function body never ran."

> "Thirteen forty-seven tests. Zero failures."

---

## CHANGES FROM REV 5

- Added full HOW TO RECORD section (OBS, ffmpeg, terminal setup, credential setup, dry-run checklist)
- `custodian demo cycle` now makes a real Stripe test-mode PaymentIntent — voiceover updated to say "A real Stripe payment"
- `custodian demo cycle` step 2 now calls real `_evaluate()` — no longer fake printed logic
- Test count: 1,346 → 1,347
- Slide instructions added (how to make the 3 close cards)
- Kill switch clear command added to pre-record checklist

---

*Total voiceover: ~130 words, ~24 seconds at 150 wpm. The other 81 seconds is the demo running and the silent close slides.*
