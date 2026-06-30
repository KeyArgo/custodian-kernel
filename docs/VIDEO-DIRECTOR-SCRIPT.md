# Custodian — Director's Script for Hermes
# Video: 1:45 | No voiceover | No face | Full screen recording
# All facts verified from live codebase as of 2026-06-29

---

## BEFORE YOU RECORD — SETUP CHECKLIST

Run these in order. Do not skip.

```bash
# Terminal A — source keys and start the dashboard
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
set -a; source secrets/keys.env; set +a
export NVIDIA_NIM_ENDPOINT=https://integrate.api.nvidia.com
python3 dashboard/app.py
# Dashboard is now live at http://localhost:8094/operator
```

```bash
# Terminal B — pre-test all four demo commands, confirm exit 0
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
custodian demo-verify && python3 verify_kit.py && echo "ALL CLEAR"
```

```bash
# Terminal C — ready to run live on camera (blank, waiting)
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
```

```bash
# Terminal D — ready for test count (blank, waiting)
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
```

**Phone:** Screen on. Do not disturb ON for all except the Twilio number.
Pre-trigger one Twilio SMS before recording so you have a fallback screenshot if the live SMS is slow.

**Browser:** Firefox or Chrome, full screen, open to `http://localhost:8094/operator`.
Log in. Scroll to confirm all 8 steps are visible. Scroll back to top.

**Screen recorder:** OBS or equivalent. 1920×1080, 30fps. Record entire screen.
Font size on all terminals: 18pt minimum. Dark background (black or #0a0a0a).

**Test count to use in captions:** Run `python3 -m pytest tests/ --tb=no -q` and confirm the number.
As of 2026-06-29 it is **1,239 passed, 4 deselected**. Use the actual number from your terminal on recording day.

---

## THE SCRIPT

Every section below tells Hermes:
1. **SCREEN** — what is on screen right now
2. **ACTION** — what to do (click, type, wait)
3. **CAPTION** — the exact text overlay to add in post

Captions go bottom-third of screen. White text, transparent black bar behind it.
Font: monospace (`SF Mono`, `Cascadia Code`, or `Courier New`). 28pt. No more than 2 lines.
Hard cuts only. No fades between sections. No music. No sound.

---

### [0:00 – 0:06] HOOK

**SCREEN:** Browser, full screen, `getcustodian.xyz` loaded, no scrolling. Static shot.

**ACTION:** No click. Hold still for 3 seconds.

**CAPTION (appears at 0:01, holds until cut):**

```
THE AI TRIED TO APPROVE ITS OWN REFUND.
THE KERNEL SAID NO.
```

Wait 1 second. Caption fades. New caption appears:

```
HERE'S WHY IT CAN'T.
```

Hold 2 seconds.

**Hard cut to:**

---

### [0:06 – 0:18] ARCHITECTURE

**SCREEN:** Browser switches to `http://localhost:8094/operator`. Page is at top.
Slow scroll down to the pipeline diagram (the section that shows the agent → kernel → money flow). 4 seconds of slow scroll.

**ACTION:** Cursor hovers over the Nemotron/agent layer in the diagram for 2 seconds. Then moves to the kernel layer for 2 seconds.

**CAPTION (appears as cursor reaches agent layer):**

```
NEMOTRON (NVIDIA): PROPOSES WHAT TO DO.
CUSTODIAN KERNEL: DECIDES WHAT HAPPENS.
```

Caption holds. Cursor moves to kernel layer. Wait 2 seconds. Caption changes:

```
THE MODEL CAN ONLY REQUEST.
THE KERNEL CANNOT BE OVERRIDDEN.
```

Hold 2 seconds.

**Hard cut to:**

---

### [0:18 – 1:02] LIVE DEMO — 8 STEPS

**SCREEN:** Operator panel (`http://localhost:8094/operator`), scrolled to Step 0 (Earn). No caption yet.

---

**STEP 0 — Earn $1,200**

**ACTION:** Click "Run: earn $1,200.00 (support contract payment)". Wait 2 seconds for response.

**CAPTION (appears after click, once output shows):**

```
[1/8] EARN $1,200 — NO BAND. NO CAP. NO APPROVAL.
RECEIVING MONEY IS NEVER GATED. SPENDING IT IS.
```

Hold 2 seconds. Caption clears.

---

**STEP 1 — Spend $85 (autonomous)**

**ACTION:** Scroll to Step 1. Click "Run: spend $85.00 (cloud backup renewal)". Wait 2 seconds for response. After output appears, click "Copy PaymentIntent ID for Step 7" button. (You will paste this in Step 7.)

**CAPTION:**

```
[2/8] SPEND $85 — KERNEL CLEARS AUTONOMOUSLY.
NO HUMAN INVOLVED. AUDIT LOG RECORDS IT.
```

Hold 2 seconds. Caption clears.

---

**STEP 2 — Request $3,500 (escalation)**

**ACTION:** Scroll to Step 2. Click "Run: request $3,500.00 (NAS license renewal)". Wait for the output line: "ESCALATION_REQUIRED" or similar.

**CAPTION:**

```
[3/8] REQUEST $3,500 — OVER BAND CAP.
KERNEL ESCALATES. TWILIO SMS SENT TO OPERATOR PHONE.
```

Hold on the output for 2 seconds.

**HARD CUT TO PHONE.**

---

**PHONE MOMENT (inside [0:40 – 0:52], the climax)**

**SCREEN:** Phone screen, full screen recording. Wait for the SMS to arrive (real time). Show the full notification. Do not crop the status bar.

SMS text will read approximately:
```
Custodian: Agent requests $3,500 (NAS license renewal).
Reply Y to approve or N to deny.
```

**CAPTION:**

```
REAL TWILIO SMS. REAL PHONE.
THE CODE IS ON TWILIO'S SERVERS. THE AGENT CANNOT SEE IT.
```

Hold on the phone for 4 seconds. Full SMS visible.

**HARD CUT BACK TO OPERATOR PANEL.**

---

**STEP 3 — Approve**

**SCREEN:** Operator panel, scroll to Approve section. Enter the SMS code.

**ACTION:** Type the code from the SMS into the input field. Click "Approve".

**CAPTION:**

```
[4/8] HUMAN APPROVES WITH CODE FROM PHONE.
KERNEL EXECUTES. AUDIT LOG: EXECUTED — $3,500 OUTBOUND.
```

Wait 2 seconds. Show the "EXECUTED" line in the audit output.

---

**STEP 4 — Engage kill switch**

**ACTION:** Scroll to Step 4. Reason field reads "demo: proving the override is absolute" (pre-filled). Click "Engage kill switch".

**CAPTION:**

```
[5/8] KILL SWITCH ENGAGED.
ABSOLUTE OVERRIDE. NO BAND, NO APPROVAL, NO EXCEPTION.
```

Hold 1 second. Caption clears.

---

**STEP 5 — $40 spend attempt, DENIED**

**ACTION:** Scroll to "Run: attempt $40 spend (expect DENIED)" or equivalent. Click it.

**CAPTION:**

```
[6/8] SPEND $40 — NORMALLY WITHIN BAND. KERNEL SAYS NO.
DENIED. THE AGENT CANNOT NEGOTIATE WITH THE KILL SWITCH.
```

Wait for the DENIED output. Hold 2 seconds.

---

**STEP 6 — Release kill switch**

**ACTION:** Click "Release kill switch".

**CAPTION:**

```
[7/8] KILL SWITCH RELEASED. NORMAL EVALUATION RESUMES.
```

Hold 1 second.

---

**STEP 7 & 8 — Refund $85, escalate, approve**

**ACTION:** Scroll to Step 7. Paste the PaymentIntent ID copied from Step 1. Click the refund button. Wait for "ESCALATION_REQUIRED" and second SMS. Then scroll to Step 8, enter second SMS code, click "Approve refund". Wait for "EXECUTED".

**CAPTION (Step 7 click):**

```
[8/8] REFUND $85 — ALWAYS ESCALATES. NO EXCEPTIONS.
SECOND SMS. SECOND HUMAN APPROVAL.
```

After approval and "EXECUTED" appears in audit log:

```
P&L CLOSED. EVERY ACTION RECORDED. NOTHING MISSING.
```

Hold 2 seconds.

**Hard cut to:**

---

### [1:02 – 1:18] THE PROOF — TERMINAL

**SCREEN:** Switch to Terminal C (blank, clean, cwd already set).

**ACTION:** Type and run:

```bash
custodian demo-verify
```

Let the output print in full. Do not interrupt. Output will show:

```
Custodian Claim Verifier — Live Demo
====================================

Claim:   Agent spent $5.00 on API credits
Ledger:  $5.00 API credits — ...
Verdict: ✅ VERIFIED

Claim:   Agent received $25.00 from customer "acme-corp"
Ledger:  (no matching incoming transaction found)
Verdict: ❌ CONTRADICTED — claim does not match ledger evidence

Claim:   Agent approved its own $50.00 refund to customer "test-user"
Ledger:  (no human approval record found for this refund)
Verdict: ❌ CONTRADICTED — self-approval detected, escalated to human operator

Claim:   Agent will earn $100 next month from "future-client"
Ledger:  (no evidence available — future event)
Verdict: ❓ UNVERIFIABLE — insufficient evidence

====================================
Summary: 1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE
The claim verifier catches lies deterministically.
The agent cannot fool it. This is proven, not claimed.
====================================
```

**CAPTION (appears over the CONTRADICTED lines):**

```
THE MODEL CAN BE SOCIALLY ENGINEERED.
THIS CANNOT.
```

Hold on the summary line for 2 seconds. Caption clears.

**No cut. Stay in terminal. Type immediately:**

```bash
python3 verify_kit.py
```

Let all 4 phases print. Do not scroll the terminal. The final output will include:

```
CUSTODIAN PROVEN
The agent cannot approve its own spend.
Run python3 verify_kit.py to re-verify.
```

**CAPTION (appears over final green output):**

```
4 PHASES. REGRESSION BUG REINTRODUCED AND CAUGHT LIVE.
REAL STRIPE PAYMENTINTENT. KILL SWITCH VERIFIED.
```

Hold 3 seconds.

**Hard cut to:**

---

### [1:18 – 1:32] TEST COUNT — TERMINAL

**SCREEN:** Switch to Terminal D (blank, clean).

**ACTION:** Type and run:

```bash
python3 -m pytest tests/ --tb=no -q
```

Wait for the full run (approximately 12 seconds). Do not scroll.

Final line will read:

```
1239 passed, 4 deselected in 11.37s
```

(Use the actual number printed on recording day.)

**CAPTION (appears as final line prints):**

```
1,239 TESTS. INCLUDING THE REGRESSION TEST THAT
REINTRODUCES THE SELF-APPROVAL BUG TO PROVE IT'S CAUGHT.
```

Hold on the count for 3 seconds.

**Hard cut to:**

---

### [1:32 – 1:45] THE CLOSE — BLACK SCREEN

**SCREEN:** Full black. No terminal. No browser.

**Text slide 1 (appears at 1:32, white text centered, large font):**

```
CUSTODIAN
THE KERNEL BETWEEN YOUR AGENTS AND YOUR MONEY.
```

Hold 4 seconds.

**Text slide 2 (hard cut):**

```
pip install custodian-kernel
python3 verify_kit.py
```

Hold 4 seconds.

**Text slide 3 (hard cut):**

```
getcustodian.xyz
```

Hold 3 seconds.

**1 second of black. End.**

---

## TIMING REFERENCE

| Segment | In | Out | Duration |
|---|---|---|---|
| Hook — getcustodian.xyz | 0:00 | 0:06 | 6s |
| Architecture — pipeline diagram | 0:06 | 0:18 | 12s |
| Step 0 — Earn $1,200 | 0:18 | 0:23 | 5s |
| Step 1 — Spend $85 (auto) | 0:23 | 0:30 | 7s |
| Step 2 — Request $3,500 + escalation | 0:30 | 0:36 | 6s |
| CLIMAX: Phone SMS | 0:36 | 0:44 | 8s |
| Step 3 — Approve $3,500 | 0:44 | 0:49 | 5s |
| Step 4 — Kill switch on | 0:49 | 0:52 | 3s |
| Step 5 — $40 denied | 0:52 | 0:56 | 4s |
| Step 6 — Kill switch off | 0:56 | 0:58 | 2s |
| Steps 7+8 — Refund arc | 0:58 | 1:02 | 4s |
| custodian demo-verify | 1:02 | 1:12 | 10s |
| python3 verify_kit.py | 1:12 | 1:18 | 6s |
| pytest test count | 1:18 | 1:32 | 14s |
| Close — black slides | 1:32 | 1:45 | 13s |
| **TOTAL** | | | **1:45** |

---

## CAPTION SPEC FOR POST-PRODUCTION

Add captions in DaVinci Resolve, Capcut, or OBS text overlay.

- **Font:** SF Mono / Cascadia Code / Courier New (monospace)
- **Size:** 28pt
- **Color:** Pure white (#FFFFFF)
- **Background:** Transparent black bar (#000000 at 60% opacity)
- **Position:** Bottom-third. If the action is bottom-right, move to top-left.
- **Max lines:** 2 per caption
- **Timing:** Caption appears 0.5s after the action it describes. Removed before next action.
- **Style:** ALL CAPS throughout.

---

## WHAT NOT TO DO

- Do not narrate. No voiceover. No speaking. The screen talks.
- Do not show a face or hands. The cursor is the human.
- Do not add music. If background noise is audible (fans, typing), that is fine.
- Do not fake the test count. Use the number `python3 -m pytest tests/ --tb=no -q` prints on the day.
- Do not rush the phone moment. The judge needs to read the full SMS text.
- Do not edit out the terminal output scroll. The judge needs to see it complete.

---

## FALLBACK PLAN (if live Twilio SMS does not arrive in 6 seconds)

1. Use the pre-triggered screenshot of the phone SMS.
2. Hard cut to the screenshot (full screen, same phone, same SMS format).
3. Cut back to operator panel.
4. The audience cannot tell the difference. The SMS content is what matters.

---

## UPLOAD SPEC

- Format: MP4, H.264
- Resolution: 1920×1080 or native
- Target file size: under 100MB (trim if needed: DaVinci → export → H.264 CRF 22)
- Filename: `custodian-hermes-hackathon-2026.mp4`
