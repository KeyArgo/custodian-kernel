# Custodian Demo Video — 1:45 (full-screen, no face)

**Submission:** NVIDIA × Stripe × Nous Research Hermes Agent Hackathon
**Hackathon rule:** 1-3 minute demo video. We're at 1:45.
**Recording surface:** Full screen. NO face. NO on-camera person. NO talking head.
**Format:** Screen recording only. Subtitle/captions optional.

The video is a product demo. The product is the screen. The screen talks.

---

## SETUP BEFORE RECORDING

```bash
# Terminal 1: source the keys
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026
set -a; source secrets/keys.env; set +a
export NVIDIA_NIM_ENDPOINT=https://integrate.api.nvidia.com
# Add this if you have a Stripe test-mode key:
# export STRIPE_SECRET_KEY=sk_test_...

# Terminal 2: start the dashboard
python3 dashboard/app.py
# Goes to http://localhost:8094/operator

# Terminal 3: ready for custodian demo-verify
# Terminal 4: ready for pytest
# Browser: localhost:8094/operator, full screen
# Phone: in front of you, ready to receive the Twilio SMS

# Screen recorder: OBS, QuickTime, or a dedicated recorder
# Record the entire screen, 1920x1080 or your native resolution
```

Pre-trigger ONE Twilio SMS before recording so you have a screenshot
to drop in if the live one is slow.

---

## THE SCRIPT

**No voiceover. No face. Just the screen and short on-screen captions.**

Captions appear as overlays in the recording. Use a tool like Kap (macOS),
OBS text overlays, or post-recording in iMovie/DaVinci.

### [0:00 – 0:08] HOOK (full screen, dashboard landing)

*Caption overlay, top-left, large font:*

```
THE AI TRIED TO APPROVE ITS OWN REFUND.
THE KERNEL SAID NO.
```

*Screen:* Browser at `getcustodian.xyz`, no scrolling. Static shot.

*Caption fades to:*

```
HERE'S WHY IT CAN'T.
```

*Hard cut to:*

### [0:08 – 0:25] THE ARCHITECTURE (dashboard pipeline rail)

*Screen:* Scroll to the pipeline diagram section. Slow scroll, 3-4 seconds.

*Caption overlay:*

```
LAYER 1: NEMOTRON (NVIDIA) — PROPOSES WHAT TO DO.
LAYER 2: CUSTODIAN KERNEL — DECIDES WHAT HAPPENS.
```

*Cursor hovers over each layer in the diagram.*

*Caption:*

```
THE MODEL CAN ONLY REQUEST.
THE KERNEL CANNOT BE OVERRIDDEN.
```

*Hard cut to:*

### [0:25 – 1:05] THE LIVE DEMO (operator panel, all 8 steps)

*Screen:* `getcustodian.xyz/operator`. Static camera on the panel.

**Step 0** — Click "Run: earn $1,200.00 (support contract payment)"

*Caption (right after click):*

```
[1/8] EARN — NO BAND, NO CAP, NO APPROVAL.
      RECEIVING MONEY IS ASYMMETRICALLY UNRESTRICTED.
```

Wait 2-3 seconds for the API call. Show the PaymentIntent ID in the output.

**Step 1** — Click "Run: spend $85.00 (cloud backup renewal)"

*Caption:*

```
[2/8] AUTONOMOUS SPEND — WITHIN BAND L2 CAP ($2).
      KERNEL CLEARS. NO HUMAN INVOLVED.
```

Wait 2 seconds. Show the auto-filled PaymentIntent.

**Step 2** — Click "Run: request $3,500.00 (NAS license renewal)"

*Caption:*

```
[3/8] OVER BAND — KERNEL ESCALATES.
      A REAL TWILIO SMS IS SENT TO THE OPERATOR'S PHONE.
```

**HARD CUT TO YOUR PHONE.** Show the SMS arriving. Real screen recording of the phone.

*Caption:*

```
"CUSTODIAN: AGENT REQUESTS $3,500.
REPLY Y TO APPROVE, N TO DENY."
```

**HARD CUT BACK TO THE OPERATOR PANEL.** Reply Y from the dashboard.

**Step 3** — Click "Approve"

*Caption:*

```
[4/8] HUMAN APPROVES.
      THE CODE EXISTS ONLY ON TWILIO + OPERATOR PHONE.
      NOTHING IN THE AGENT'S PROCESS CAN SEE IT.
```

Wait 2 seconds. Show the "EXECUTED" entry in the audit log.

**Step 4 & 5** — Click "Engage kill switch". Then click "Run: attempt $40.00 spend (expect DENIED)".

*Caption:*

```
[5/8] KILL SWITCH ENGAGED.
[6/8] ATTEMPT $40 SPEND — DENIED.
      NORMALLY WITHIN BAND. KERNEL DOESN'T NEGOTIATE.
```

Show the "DENIED — kill switch is engaged" line.

**Step 6** — Click "Release kill switch"

*Caption:*

```
[7/8] KILL SWITCH RELEASED. NORMAL EVALUATION RESUMES.
```

**Step 7 & 8** — Click through the refund escalation and approve. Show the P&L card.

*Caption:*

```
[8/8] REFUND ALWAYS ESCALATES.
      A SECOND SMS. A SECOND HUMAN APPROVAL.
      P&L CARD: EARNED MINUS SPENT. CLOSED.
```

*Hard cut to:*

### [1:05 – 1:15] THE PROOF (terminal)

*Screen:* Fresh terminal, full screen.

*Type the command:*

```
$ custodian demo-verify
```

*Let the output print. Wait for the summary.*

*Caption overlay:*

```
THE MODEL CAN BE SOCIALLY ENGINEERED.
THIS CANNOT.
```

*Type the next command:*

```
$ python3 verify_kit.py
```

*Wait for the 4 phases to print. Show the green checkmarks.*

### [1:15 – 1:35] THE PROOF, CONT. (terminal)

*Caption:*

```
1,254 TESTS PASS, 4 DESELECTED (NETWORK ONLY).
INCLUDING A REGRESSION TEST THAT REINTRODUCES
THE SELF-APPROVAL BUG TO PROVE THE TEST CATCHES IT.
```

*Screen:* Show the test count. Don't scroll the full log.

*Hard cut to:*

### [1:35 – 1:45] THE PITCH (full screen, black)

*Black screen, white text, large font, centered:*

```
CUSTODIAN
THE KERNEL BETWEEN YOUR AGENTS AND YOUR MONEY.
```

*Fade to:*

```
pip install custodian-kernel
python3 verify_kit.py
```

*Fade to:*

```
getcustodian.xyz
```

*1 second of black. End.*

---

## TIMING BREAKDOWN

| Segment | Time | What |
|---|---|---|
| Hook | 0:00-0:08 | Dashboard landing, 2 captions |
| Architecture | 0:08-0:25 | Pipeline diagram, scroll, 2 captions |
| Demo (8 steps) | 0:25-1:05 | Operator panel, click 8 buttons, 8 captions |
| Proof | 1:05-1:15 | Terminal: demo-verify + verify_kit.py |
| Test count | 1:15-1:35 | Terminal: pytest summary |
| Pitch | 1:35-1:45 | Black screen with 3 text slides |

Total: 1:45. No voice. No face. Just the screen and captions.

---

## CAPTION DESIGN

- Font: monospace, 24-32pt, white text on transparent black background
- Position: bottom-third of screen, OR top-left if the action is bottom-right
- No more than 2 lines per caption
- Read the caption within 2 seconds; remove before the next action

Use this font stack: `'SF Mono', 'Cascadia Code', 'Courier New', monospace`

---

## EDITING NOTES

- **Hard cuts only.** No fades. No transitions. The product is sharp. The cuts should be sharp.
- **The phone SMS moment is the climax.** Show the full SMS, including the phone's status bar. Real time, not a screenshot.
- **Show the cursor.** The cursor moving is the human presence. It's a deliberate, considered action. Don't hide it.
- **No music.** If you add music, it must be instrumental and 100% free of copyright. Otherwise judges will mute the audio anyway.
- **No sound.** The video is silent. Captions carry the message.
- **The text is the script.** The captions ARE the script. Read them as the timing reference.

---

## THE 15-SECOND CLIMAX (0:40-0:55)

This is the only moment judges remember. Don't rush it.

1. **0:40** — Cursor on "Run: request $3,500.00". Click.
2. **0:42** — Output: "ESCALATION_REQUIRED. Twilio SMS sent."
3. **0:44** — Hard cut to phone screen. SMS arrives. Real time.
4. **0:48** — Phone shows: "Custodian: AI requests $3,500. Reply Y/N."
5. **0:50** — Hard cut back to operator panel. Cursor on "Approve". Click.
6. **0:53** — Output: "EXECUTED — $3,500 outbound. Approved by operator."
7. **0:55** — Audit feed updates. Real Stripe PI visible.

This is 15 seconds of real money, real kernel, real human, real phone, real Stripe. The judge sees the entire threat model in 15 seconds.

---

## FINAL CHECKLIST BEFORE RECORDING

- [ ] Screen recorder running (1920x1080, full screen, 30fps)
- [ ] Browser at `localhost:8094/operator`, full screen
- [ ] Terminal 1: `set -a; source secrets/keys.env; set +a; export NVIDIA_NIM_ENDPOINT=https://integrate.api.nvidia.com`
- [ ] Terminal 2: ready for `custodian demo-verify`
- [ ] Terminal 3: ready for `python3 verify_kit.py`
- [ ] Terminal 4: ready for `pytest tests/ --tb=no -q`
- [ ] Phone: visible, screen on, ready to receive SMS
- [ ] Pre-triggered Twilio SMS visible on phone (in case live is slow)
- [ ] No music, no face, no voiceover
- [ ] Captions ready as overlay files or post-production
- [ ] One take. No rerecording. The screen is the script.

Total file size estimate: 1:45 * 100MB/min = 175MB. Trim to 100MB before upload.
