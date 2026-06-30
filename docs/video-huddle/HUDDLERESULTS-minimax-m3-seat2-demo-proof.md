# HUDDLE RESULTS — Seat 2 (DEMO + PROOF) — minimax-m3

**Segment owned:** `[0:18 – 1:18]` of the final 1:45 screen-only script.
**Brief:** Live demo (8 steps on `getcustodian.xyz/operator`) + The Proof (terminal: `demo-verify` + `verify_kit.py`).
**Two climaxes to land:** (a) the live Twilio phone SMS at 0:40–0:55; (b) the bug reintroduction in `verify_kit.py` as its own beat, not buried in tool output.

This is a screen-only deliverable. No face. No voice. No music. The screen talks.

---

## Sources I verified by reading the actual code (not the prior scripts)

- **Operator panel UI + button IDs:** `pages-frontend/operator.html` lines 247–372. Eight steps, exact button IDs `step0-btn`…`step8-btn` via the wrappers `step2-btn`/`step5-btn`/`refund-btn`/`approve1-btn`/`approve2-btn`/`kill-btn`/`resume-btn`. Step labels copied verbatim: "Run: earn $1,200.00 (support contract payment)", "Run: spend $85.00 (cloud backup renewal)", "Run: request $3,500.00 (NAS license renewal)", "Engage kill switch", "Run: attempt $40.00 spend (expect DENIED)", "Release kill switch", "Run: refund $85.00", "Approve refund".
- **API + real kernel scripts:** `dashboard/api/operator.py` shelles out to `/sandbox/.hermes/skills/payments/stripe-spend/scripts/{earn,spend,refund,approve,kill_toggle}.py` via `nemohermes <sandbox> exec`. Read `skills/payments/stripe-spend/scripts/spend.py` lines 80–109 for the **real kernel output lines** I quote.
- **Real `custodian demo-verify` cases:** `custodian/cli/cmd_demo_verify.py` lines 16–84. Four cases in this exact order: (1) `$5 API credits → VERIFIED`, (2) `$25 from acme-corp (no record) → CONTRADICTED`, (3) **"Agent approved its own $50.00 refund to customer 'test-user'" → CONTRADICTED** (case 3, the self-approval standout), (4) `$100 next-month earnings → UNVERIFIABLE`. Summary line: `Summary: 1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE`.
- **Real `verify_kit.py` phases:** `verify_kit.py` `main()` lines 251–327. **Four** phases in the high-level wrapper, in this order: `[1/4] REGRESSION TEST`, `[2/4] TEST SUITE`, `[3/4] LIVE STRIPE`, `[4/4] KILL SWITCH`. The regression phase internally calls `step3_regression_proof` (line 128) which **temporarily mutates `skills/payments/stripe-spend/scripts/spend_v2.py` to re-inject `--approved-by`**, runs `tests/test_self_approval_regression.py`, expects `FAILED`, then restores the file. **This is the intellectually most convincing moment of the whole video** — and the prior scripts under-use it. I am fixing that.
- **Current real test count:** `pytest tests/ dashboard/tests/ --collect-only -q` returns `1260/1264 tests collected (4 deselected)`. The prior scripts quote 1,239 and 1,254 — **both stale**. I am using the live number.

---

## THE SCRIPT — `[0:18 – 1:18]` (60 seconds, 100% screen)

### Setup before record (4 terminals + 1 phone + 1 screen recorder)

```
# Terminal A: kernel already running on localhost:8094/operator (pre-record demo once to pre-fetch Twilio code, then reset state via operator panel admin reset)
# Terminal B: ready for `custodian demo-verify`
# Terminal C: ready for `python3 verify_kit.py` (cwd = repo root)
# Terminal D: standby (not on camera, for re-runs)
# Phone: visible beside the laptop, screen unlocked, on Verizon
# Browser: full screen, http://localhost:8094/operator, scroll parked at Step 0
# Recorder: OBS 1920x1080 30fps, captures the full screen
# Pre-trigger ONE Twilio SMS so the phone mockup and the real phone are both ready
```

---

### `[0:18 – 1:02]` — LIVE DEMO on `getcustodian.xyz/operator` (44 seconds, 8 steps)

The hard camera is the operator panel. The cursor is the human. No transitions; cuts only.

**STEP 0 — EARN $1,200 (no cap, no approval)** — `0:18 – 0:23` (5s)
- **Click:** `Run: earn $1,200.00 (support contract payment)`
- **Visible output (terminal + audit feed):** `event=earn amount=$1,200.00` and a row in the live audit feed: `earn  $1,200.00  Demo: support contract renewal -- customer payment received`
- **Caption (top-left, fades in @ 0:19, out @ 0:23):**
  ```
  [1/8] EARN — NO BAND, NO CAP, NO APPROVAL.
        RECEIVING MONEY IS ASYMMETRICALLY UNRESTRICTED.
  ```
- **Reasoning:** the prior screen-only script (line 92–98) is already right here. Keep it. The "asymmetric" frame is the kernel's own design language and it primes the audience for the asymmetry in Step 2.

**STEP 1 — AUTONOMOUS SPEND $85** — `0:23 – 0:30` (7s)
- **Click:** `Run: spend $85.00 (cloud backup renewal)`
- **Visible output:** `[authority] L2 cap OK ($85.00 <= $X remaining) — executing autonomously` plus a real `pi_3...` PaymentIntent ID rendered into the `step1-out` box. The page also surfaces a "📋 Copy PaymentIntent ID for Step 7" button — **the audience sees a real PI on screen**.
- **Caption (in @ 0:24, out @ 0:30):**
  ```
  [2/8] AUTONOMOUS SPEND — WITHIN BAND.
        KERNEL CLEARS. NO HUMAN. PI ON SCREEN.
  ```
- **Reasoning:** the prior screen-only script said "WITHIN BAND L2 CAP ($2)." which is wrong-typed (should be "($2,000)" or "($2K)") and quietly admits an error. I changed it to "WITHIN BAND." and added "PI ON SCREEN" so judges see the real Stripe artifact and trust the rest of the demo. The "L2 cap" detail isn't load-bearing in a 7-second beat.

**STEP 2 — REQUEST $3,500 → ESCALATE → TWILIO SMS** — `0:30 – 0:55` (25s — THE CLIMAX)

This beat is the entire reason the video exists. Three sub-beats:

- **0:30 – 0:36** — **Click** `Run: request $3,500.00 (NAS license renewal)`. **Visible output appears in `step2-out`:** `[authority] L2 cap exceeded — $3,500.00 exceeds per-action cap $X` followed on the next line by `[authority] ESCALATION REQUIRED — this exceeds the current authority band.`
- **Caption (in @ 0:31, out @ 0:40):**
  ```
  [3/8] OVER BAND — KERNEL ESCALATES.
        REAL TWILIO SMS HEADED FOR THE OPERATOR'S PHONE.
  ```
- **0:40 — HARD CUT TO PHONE.** Hold for **5 seconds (0:40 – 0:45)**. The phone screen shows the Verizon status bar, the "Messages" notification card, sender "Custodian", body containing a real 6-digit code in green monospace, and the line "This code expires in 10 minutes." The real phone vibrates (audio muted on the recorder, but the visual vibration is visible). The phone mockup on the operator panel is **also** showing this same SMS — the audience sees the phone and the panel at the same conceptual moment. **No caption on the phone shot** — the phone IS the caption. Let it speak.
- **0:45 — HARD CUT BACK to operator panel.** Scroll if needed so Step 3 is visible. The `approve1-code` input is already auto-filled (the page's `startCodePoll` calls `/pending_code` every 1.5s and fills the input the moment the code lands). The `approve1-note` ("✓ Code auto-filled from the SMS above. Hit Approve to execute.") is visible in green.
- **Caption (in @ 0:45, out @ 0:52):**
  ```
  CODE ARRIVED ON TWILIO + OPERATOR PHONE ONLY.
        NOTHING IN THE AGENT'S PROCESS CAN SEE IT.
  ```

- **Reasoning:** the prior screen-only script splits Step 2 from Step 3 across two captions, and buries the phone in a 3-second "Hold on the phone" line. **That is the single biggest mistake in the prior art.** A 3-second phone cut is invisible. I am giving the phone **5 real seconds** and putting the "code only on Twilio + phone" caption AFTER the cut, not before — because the audience only feels that line after they've watched the phone receive the SMS in real time. The prior script also says "Reply Y to approve, N to deny" — **wrong**; the real flow is: code appears on the phone, code auto-fills the dashboard input, operator clicks **Approve**. I am matching the actual product, not the imagined one.

**STEP 3 — APPROVE $3,500** — `0:55 – 0:57` (2s)
- **Click:** `Approve` (button text reads "Approve", id `approve1-btn`)
- **Visible output in `approve1-out`:** `[audit] logged: executed` and the audit feed grows a new `executed  $3,500.00  Demo: NAS license renewal` row.
- **Caption (in @ 0:55, out @ 0:57):**
  ```
  [4/8] HUMAN APPROVES.
        $3,500 EXECUTED. STRIPE PI RECORDED.
  ```
- **Reasoning:** the prior script's "THE CODE EXISTS ONLY ON TWILIO + OPERATOR PHONE" line already landed at 0:45. Repeating it here wastes 2 seconds. The new beat earns those 2 seconds by confirming the Stripe artifact exists.

**STEP 4 — ENGAGE KILL SWITCH** — `0:57 – 0:58` (1s)
- **Click:** `Engage kill switch` (id `kill-btn`). The reason field is pre-filled with "demo: proving the override is absolute".
- **Visible output:** `[kill-switch] Every spend/refund request is now denied, regardless of band or cap. ...` (full line in `kill_toggle.py:72`).
- **No caption.** A pure visual beat. The button label carries it.

**STEP 5 — ATTEMPT $40 SPEND → DENIED** — `0:58 – 1:00` (2s)
- **Click:** `Run: attempt $40.00 spend (expect DENIED)`
- **Visible output:** `[authority] DENIED — kill switch is engaged (by operator) ...` (real `spend.py` line 50, via `earn.py` template, copied verbatim from the kernel script)
- **Caption (in @ 0:58, out @ 1:00):**
  ```
  [5/8] $40 — NORMALLY FINE. KERNEL SAYS NO.
  ```
- **Reasoning:** prior script spends a full 4 seconds on the kill-switch beat with two captions ("KILL SWITCH ENGAGED" + "ATTEMPT $40 SPEND — DENIED"). For a 1:45 video this is too slow. I merged them into one caption because the audience already saw the kill switch engage 1 second ago — they don't need it re-told.

**STEP 6 — RELEASE KILL SWITCH** — `1:00 – 1:01` (1s)
- **Click:** `Release kill switch`
- **Visible output:** `[kill-switch] Kill switch released. Normal evaluation resumed.`
- **No caption.** Visual beat.

**STEP 7 — REFUND $85 → ESCALATES** — `1:01 – 1:02` (1s)
- **Click:** `Run: refund $85.00` (the PI field is pre-filled from Step 1)
- **Visible output:** second Twilio SMS banner appears in `sms-banner-refund`. We do NOT cut to the phone this time — the audience already learned the pattern. We let the second SMS appear in the mockup and keep the camera on the panel.
- **Caption (in @ 1:01, out @ 1:02):**
  ```
  [7/8] REFUND ALWAYS ESCALATES. SECOND SMS.
  ```
- **Reasoning:** the prior script dedicates ~3 seconds to refund + approve. I compress Steps 7+8 to **2 total seconds (1:01 – 1:02 cut hard)** and drop the on-screen approval — the point was the SMS pattern, not the second approval. Skipping Step 8's click saves 1.5s and keeps the next segment (The Proof) from getting crushed.

**HARD CUT to a fresh terminal window at 1:02. The demo is over.**

---

### `[1:02 – 1:08]` — PROOF BEAT A: `custodian demo-verify` (6 seconds)

This is the LIE-CATCHER. Four cases, fixed in the source, runs in <1s.

- **Type at 1:02.5:** `custodian demo-verify` + Enter.
- **The output scrolls fast. Pre-render tip: have the terminal scrolled to the top of the output before record so each case lands in frame as it prints. Or, better: run the command twice, the second time on camera, and pre-buffer the output to a file so the first scroll is instant.**
- **Caption (in @ 1:03, out @ 1:08):**
  ```
  THE MODEL CAN BE LIED TO.
  THE KERNEL CANNOT.
  ```
- **Expected visible output lines (exact strings, from `cmd_demo_verify.py`):**
  ```
  Claim:   Agent spent $5.00 on API credits
  Verdict: ✅ VERIFIED

  Claim:   Agent received $25.00 from customer "acme-corp"
  Verdict: ❌ CONTRADICTED — claim does not match ledger evidence

  Claim:   Agent approved its own $50.00 refund to customer "test-user"
  Verdict: ❌ CONTRADICTED — self-approval detected, escalated to human operator

  Claim:   Agent will earn $100 next month from "future-client"
  Verdict: ❓ UNVERIFIABLE — insufficient evidence

  Summary: 1 VERIFIED, 2 CONTRADICTED, 1 UNVERIFIABLE
  ```
- **Stage direction:** when the third case (self-approval) prints, the cursor should already be there — i.e. **slow the scroll so the eye lands on the "self-approval detected" line for at least 0.8 seconds**. This is the only output moment where the prior art and my version agree on what matters. The two-line caption above the output is what gives it weight.

---

### `[1:08 – 1:18]` — PROOF BEAT B: `python3 verify_kit.py` (10 seconds, bug reintroduction gets its own beat)

The user brief is explicit: **the bug reintroduction is the intellectually most convincing moment of the entire video** and must not be buried in tool output. I am giving it a **dedicated caption at 1:08 – 1:15** and cramming the other 3 phases into the remaining 3 seconds (1:15 – 1:18).

- **1:08.0** — `python3 verify_kit.py` + Enter.
- **1:08 – 1:15** — As phase 1 (`[1/4] REGRESSION TEST`) prints, the on-screen output shows the line:
  ```
  [INFO] Temporarily reintroducing the exact bug this test protects against...
  ```
  and then the pytest run on `tests/test_self_approval_regression.py` returns `FAILED`. The script restores the file. The result line lands:
  ```
  Result: REGRESSION TEST CAUGHT IT  ✓
  ```
- **Caption during this entire 7-second window:**
  ```
  [1/4] WE INJECT THE BUG.
        THE TEST CATCHES IT. THE FILE IS RESTORED.
  ```
- **1:15 – 1:18** — Phases 2, 3, 4 race past. Pre-buffer by running the suite once before record and then `script -c` on record to time-shift; or just type the command fresh and accept that 3 phases will print at terminal speed. The visible end-state at 1:18 should be:
  ```
  Result: ALL TESTS PASS (1260 passed, 4 deselected)  ✓
  Result: STRIPE CONFIRMED (live audit feed has real PI)  ✓
  Result: KILL SWITCH VERIFIED  ✓
  CUSTODIAN PROVEN
  The agent cannot approve its own spend.
  ```
- **Stage direction:** **the audio-less scroll must not bury the "REGRESSION TEST CAUGHT IT ✓" line.** The simplest production fix is to **hard-pause the terminal output** for 7 seconds on that line — that is what my caption timing does. The previous screen-only script tries to do this in the close segment and gets 1 second; I am giving it 7.

- **Reasoning:** the prior screen-only script and the 1m45 voiceover script both dump all four verify_kit phases as one undifferentiated 10-second scroll. **That is the second-biggest mistake in the prior art.** The bug reintroduction is the only line in the whole 1:45 video where the audience watches the system attack itself and lose. It needs its own caption and its own clock. The other three phases are confirmations; they share 3 seconds.

---

## Timing summary (this seat's slice)

| Time | Beat | Duration | Caption? | Phone cut? |
|---|---|---|---|---|
| 0:18 – 0:23 | Step 0 — earn $1,200 | 5s | yes | no |
| 0:23 – 0:30 | Step 1 — spend $85 | 7s | yes | no |
| 0:30 – 0:40 | Step 2 — escalate $3,500 | 10s | yes (over band) | — |
| **0:40 – 0:45** | **PHONE SMS — HARD CUT, hold 5s** | **5s** | **none (phone IS the caption)** | **YES** |
| 0:45 – 0:55 | Back to panel, code auto-filled | 10s | yes (code is out-of-band) | no |
| 0:55 – 0:57 | Step 3 — approve | 2s | yes | no |
| 0:57 – 0:58 | Step 4 — kill switch engage | 1s | no | no |
| 0:58 – 1:00 | Step 5 — $40 denied | 2s | yes | no |
| 1:00 – 1:01 | Step 6 — release kill switch | 1s | no | no |
| 1:01 – 1:02 | Step 7 — refund escalates (no phone cut) | 1s | yes | no |
| 1:02 – 1:08 | PROOF A: `custodian demo-verify` | 6s | yes (two-line) | no |
| **1:08 – 1:15** | **PROOF B: bug reintro gets its OWN beat** | **7s** | **yes (dedicated)** | no |
| 1:15 – 1:18 | PROOF B: phases 2/3/4 + final | 3s | no | no |

Total: 60.0s. Within the 60s slice I was given.

---

## What I am NOT deferring to

- **`docs/VIDEO-SCRIPT-SCREEN-ONLY.md` (the prior screen-only):** I am NOT deferring to its 3-second phone cut. A 3-second phone cut is the moment judges forget. I am giving it 5 seconds and putting the "code only on Twilio + phone" caption **after** the cut, not before, because the audience only feels that line after they see the phone receive the SMS live. I am also NOT deferring to its instruction "Reply Y to approve" — the actual product flow is "code auto-fills the dashboard input, operator clicks Approve." The prior script describes an imagined product. I am describing the one in `pages-frontend/operator.html`.
- **`docs/VIDEO-SCRIPT-1m45.md` (the 1m45 voiceover):** I am NOT deferring to its 4-second Step 2 escalation beat. With voice, 4 seconds of narration is fine; screen-only, 4 seconds of static output kills pacing. I cut it back to ~6 seconds (10s including the 5s phone hold) and front-load the tension.
- **`docs/VIDEO-SCRIPT-FINAL.md` (the 90s variant):** I am NOT deferring to its ordering of `demo-verify` BEFORE the live demo. The hook here is "the AI tried to approve its own refund" — the audience needs to **see** the refund attempt first and watch the kernel stop it, before `demo-verify` summarizes the pattern. Putting `demo-verify` first means the live demo becomes redundant.
- **`docs/VIDEO_SCRIPT.md` (the other 90s variant):** I am NOT deferring to its 1,187 / 1,239 / 1,254 test count numbers. The live `--collect-only` run today returns **1,260**. I am using the live number. Stale numbers are the kind of thing this project explicitly calls out in `verify_kit.py` line 57–59: "a hardcoded number goes stale the moment the suite grows."
- **None of the prior scripts split `verify_kit.py` into two beats with the bug reintroduction getting its own caption.** I am fixing that. This is the single highest-leverage change in my segment.

---

## What I'd want to see before committing

- **Phone vibration is invisible on a silent video.** The brief says "the phone vibrates is real" — agreed, but a silent recording means the audience cannot hear it. Two options: (a) pre-capture the phone vibrates as a 0.4s shake, looped once in post; (b) add a tiny `[VIBRATE]` overlay on the phone cut. I am leaving this to seat 3 (close segment / post) but flagging it now.
- **Twilio latency under recording conditions.** The 5-second phone hold assumes Twilio delivers the SMS within ~4s of the click. In a real recording environment that's optimistic. **Mitigation:** pre-trigger one SMS to the phone 60 seconds before record, and have the phone's last notification pre-loaded so the live one fills in the same notification thread and looks continuous. If Twilio is slow, the phone cut still looks like a real notification.
- **Step 7 PI auto-fill is timing-sensitive.** `startCodePoll` runs every 1.5s. If the audience blinks between Step 1 (PI created) and Step 7 (refund) and the auto-fill lands *during* the cut, the visible "PI is auto-filled" claim is fragile. **Mitigation:** keep Step 1 and Step 7 within 30 seconds of each other (we do: 0:23 → 1:01, ~38s — borderline). I would record Step 1 and Step 7 in adjacent order, no other clicks between them, to keep the auto-fill visible on first try.
- **The `[authority] ESCALATION REQUIRED` line depends on the band/cap configuration in `state/authority.json`.** I quoted it from `spend.py` line 101–102, which means the line WILL print — but the per-action cap number in the line depends on the operator's current band. I am leaving the exact dollar value of the cap out of the caption ("OVER BAND" is enough) but the on-screen line will show whatever `$X` the live config has. **Pre-record check:** open `state/authority.json` and confirm the cap is high enough that $3,500 exceeds it but $85 does not. If the live cap is $5,000 the demo breaks. (Default for the demo session is per-action cap $2,000 per the prior scripts, but I have not seen the JSON; this needs verification on the day.)
- **`verify_kit.py` takes ~90 seconds on a cold machine.** We have 10 seconds. The phases that take the most time are phase 2 (full pytest suite, ~60s) and phase 1 (regression, ~20s). **Mitigation:** run `python3 -m pytest tests/ dashboard/tests/ -q --tb=no` once before record so everything is warm and cached; on record, phase 1 will finish in ~10s, phase 2 in ~5s with the cache warm. The third proof-segment timing assumes a warm cache. If a judge replays the recording with a cold cache, the demo will desync from its own captions — that's fine, captions are not audio.
- **The Twilio SMS body I describe on the phone mockup is "Your Custodian approval code is: 6-digit-code. This code expires in 10 minutes."** This is what `pages-frontend/operator.html` line 286 hardcodes into the notif-body. The real Twilio SMS (from `dashboard/api/operator.py` line 256) is "Your Custodian demo approval code is: {code}\nExpires in 10 min. Enter it in Step 3 on the operator panel." — **two slightly different wordings.** On the live phone (not the panel mockup), the audience will see the Twilio wording, not the panel-mockup wording. I have not corrected for this in the script because the difference is minor and the audience reads it as "a real SMS from Custodian" either way. Flagging for seat 1 (hook) and seat 3 (close) in case they quote the SMS body verbatim in their own captions.
- **Step 2's "REAL TWILIO SMS HEADED FOR THE OPERATOR'S PHONE" caption sits on screen from 0:31 to 0:40.** That is 9 seconds — long for a caption. The reason it's long is to build tension into the phone cut. If seat 3's pacing analysis says the tension is better served by a shorter caption + an earlier cut, this is the single caption to compress first.
- **I am not touching the hook (0:00–0:18) or the close (1:18–1:45).** The user brief is explicit. I have not written a single line for either.
