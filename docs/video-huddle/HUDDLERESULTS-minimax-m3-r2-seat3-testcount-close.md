# SEAT 3 (R2) — TEST COUNT + CLOSE [1:38 – 2:03]

**Owner:** minimax-m3 (seat 3 of 3, revision 2) | **Segment:** 1:38–2:03 (25s total) | **Format:** screen + caption + voiceover (new in R2)
**Inherits from:** R1 master `docs/VIDEO-SCRIPT-FINAL.md` + my R1 seat draft `docs/video-huddle/HUDDLERESULTS-minimax-m3-seat3-testcount-close.md`
**Diff vs R1:** pushed by 20s because seat 2 inserted the `custodian earn-and-buy` beat between demo-verify and verify_kit. Test-count slot still 14s; close compresses 13s → 11s. **Voiceover layer is new in R2** (R1 was screen-only).

---

## CONSTRAINTS I AM NOT NEGOTIATING

1. Test count = **1,245**. Verified live 2026-06-29 by seat 1 of R1 (three runs). **I am not re-running pytest.** The number is what it is. If it drifts on recording day, the editor changes one token.
2. Caption must name **`test_spend_v2_has_no_approved_by_flag`** verbatim — snake_case, the literal Python identifier in `tests/test_self_approval_regression.py:53`. This is the canary.
3. Close is 11s, not 13s. Three slides on black. Each ~3.5s. Slide 3 gets 0.5s black tail. Total 11.0s on the nose.
4. Voiceover for the test-count segment is **the brief's verbatim sentence** (26 words in the spelled-out form, 10.4s at 150 wpm). Voiceover for the close is **absent** — see "What I am NOT deferring to" for why.

---

## SEGMENT 1 — TEST COUNT [1:38 – 1:52] (14 seconds)

**SCREEN:** Fresh terminal, full screen. Black or `#0a0a0a` background, monospace 18pt minimum (20pt recommended), cwd at repo root. No browser, no scroll, no prior terminal artifacts. The previous segment (seat 2's `verify_kit.py` bug-reintroduction + the new 20s `custodian earn-and-buy` beat ending at 1:38) ends on its own last printed line. **Hard cut to a new terminal window at exactly 1:38.000.**

**The exact command to type (visible keystrokes; do not type the leading `$`):**
```
python3 -m pytest tests/ --tb=no -q
```

**CAPTION (appears at 1:40.0, ~2s into the progress bar; bottom-third, white on transparent black, monospace 28pt, 2 lines max):**
```
1,245 TESTS. INCLUDES test_spend_v2_has_no_approved_by_flag —
THE REGRESSION THAT REINTRODUCES THE SELF-APPROVAL BUG.
```
- Line 1: 51 chars. Line 2: 56 chars. Both well under 80.
- Holds until 1:51.0 (11-second hold). Clears at 1:51.0.

**VOICEOVER (begins at 1:40.0, lands in sync with the caption; track layered on top of the terminal):**
> "One thousand, two hundred forty-five tests. The one that matters: the regression that reintroduces the self-approval bug — the same bug the verifier just proved couldn't be faked."

- **Word count: 26 words** (counting "1,245" as "one thousand, two hundred forty-five" = 5 words, and counting "couldn't" as 1 word). The text in the brief is 23 words when "1,245" is read as a single token ("twelve-forty-five") and "couldn't" is read as 1 word. I am spelling out the number because voiceover cannot be skimmed; a judge hearing "twelve-forty-five" mishears it. The spelled-out form is 26 words and lands at **10.4s at 150 wpm** (well inside the 14s window).
- Pacing: first 8 seconds deliver the count; final 2.4 seconds land the "couldn't be faked" punchline as the progress bars finish and `1245 passed` prints.
- The line "the same bug the verifier just proved couldn't be faked" **explicitly calls back to seat 2's `custodian earn-and-buy` beat** (the verifier just ran) and to seat 2's earlier `verify_kit.py` bug-reintroduction beat. This is the only spot in the video where three different proof mechanisms are bound into one sentence. Don't shorten it.

**ACTION (frame-by-frame for the editor):**

| Time | What the camera shows | What the editor does |
|---|---|---|
| 1:38.000 | Blank prompt, blinking cursor | Hard cut from seat 2's terminal |
| 1:38.500 | First characters of `python3` appear | No caption, no voice yet |
| 1:39.500 | Full command visible, cursor at end of line | — |
| 1:39.700 | Enter pressed; first progress dot prints | — |
| 1:40.000 | ~5% progress line visible | Caption fades in (0.3s); voiceover begins |
| 1:40 – 1:50 | Progress dots streaming, ~5% → ~95% | Caption holds; voiceover lands at 1:50.4 |
| 1:50.500 | Final line prints: `1245 passed, 4 deselected in ~14s` | Caption + voiceover both ended; hold 1.5s on the number |
| 1:52.000 | Static on final summary | **HARD CUT to black for close** |

**Why hold the progress bars instead of jumping to the summary line:** R1 explained this. The full progress bar is the only defense against the "is the terminal output faked?" objection. A 2:03 video that flashes a single line is suspicious; a 14s segment of dots streaming is not. Carry that over to R2 unchanged.

**Why voiceover here is non-negotiable in R2:** The whole point of the new 20s earn-and-buy beat is that the *verifier* (a separate product component) is what proves the kernel is honest. The test count segment is the *third* proof (after the live demo and the earn-and-buy beat). The R1 caption-only delivery can't bind those three things together — the judge has to read three captions and connect the dots. The voiceover in R2 says it once, in 10 seconds, in one sentence. This is the only R2 voiceover I'm adding; it's also the most important one.

---

## SEGMENT 2 — CLOSE [1:52 – 2:03] (11 seconds, 3 text slides on black)

**SCREEN:** Full black (#000000). No terminal. No browser. No cursor. White text only, centered, monospace.

**VOICEOVER: NONE.** The close is silent. See "What I am NOT deferring to" §3 for the reasoning. The visual carries it.

### Slide 1 — value prop — [1:52 – 1:55.5] (3.5 seconds)

```
CUSTODIAN
THE KERNEL BETWEEN YOUR AGENTS AND YOUR MONEY.
```
- Line 1: 44pt centered. Line 2: 32pt centered. White on pure black.
- Hard cut in. No fade. Hold 3.5s.

### Slide 2 — install command — [1:55.5 – 1:59] (3.5 seconds)

```
pip install custodian-kernel
python3 verify_kit.py
```
- 32pt monospace, two lines, centered. Same style as slide 1 body.
- Hard cut. Hold 3.5s.
- Both commands visible. The deliberate call: showing *both* means a judge who screenshots frame 1:56.5 has everything they need to reproduce the proof. Showing only `pip install` would be a tease; showing only `python3 verify_kit.py` would lose the install hook.

### Slide 3 — URL — [1:59 – 2:02.5] (3.5 seconds + 0.5s tail = 4.0s)

```
GETCUSTODIAN.XYZ
```
- 64pt monospace, centered, white on black. One line. The biggest text on screen for the entire video.
- Hard cut. Hold 3.5s.
- **0.5s of pure black at 2:02.5 – 2:03.0.** This is the visual breath. No fade, no music sting, no "thanks for watching." The black IS the end.

**Total close: 3.5 + 3.5 + 3.5 + 0.5 = 11.0 seconds.**

**ACTION (frame-by-frame):**

| Time | What the camera shows | What the editor does |
|---|---|---|
| 1:52.000 | Black, no text | Hard cut from `1245 passed` final line |
| 1:52.000 | Slide 1 line 1+2 visible | Hard cut in (1-frame snap, no fade) |
| 1:55.500 | Slide 1 ends | Hard cut to slide 2 |
| 1:59.000 | Slide 2 ends | Hard cut to slide 3 |
| 2:02.500 | Slide 3 ends | Hard cut to black |
| 2:03.000 | Black | End of video |

**No fades. No transitions. No music.** Hard cuts only, as established in the R1 master.

---

## TIMING SUMMARY (this seat's R2 slice)

| Time | Beat | Duration | Caption | Voiceover |
|---|---|---|---|---|
| 1:38 – 1:52 | TEST COUNT (`pytest` + named regression) | 14s | yes (2 lines, names `test_spend_v2_has_no_approved_by_flag`) | yes (26 words, 10.4s) |
| 1:52 – 1:55.5 | Close slide 1 (value prop) | 3.5s | slide IS the caption | no |
| 1:55.5 – 1:59 | Close slide 2 (install + verify_kit) | 3.5s | slide IS the caption | no |
| 1:59 – 2:02.5 | Close slide 3 (URL) | 3.5s | slide IS the caption | no |
| 2:02.5 – 2:03 | Black tail | 0.5s | — | — |
| **TOTAL** | | **25.0s** | | |

Within the 25s slice.

---

## WORD COUNT AUDIT (voiceover)

| Segment | Words | At 150 wpm | Within budget? |
|---|---|---|---|
| Test count VO | 26 | 10.4s | yes (14s window) |
| Close VO | 0 | 0.0s | yes (n/a) |
| **Total VO for this seat** | **26** | **10.4s** | yes |

---

## WHAT I AM NOT DEFERRING TO

1. **R1's "screen-only" format for the test-count segment.** R1 was a captions-only video. R2 explicitly adds a voiceover layer per the brief. I am not importing the R1 "no voiceover" decision into R2 — that decision is now wrong, and was the single biggest gap in R1. The R1 draft's seat-3 timing analysis (the 14s pytest math, the "hold the progress bars" reasoning, the font-size spec) is correct and I am carrying it forward unchanged.

2. **R1's caption wording for the test count.** I am keeping R1's two-line caption verbatim: `1,245 TESTS. INCLUDES test_spend_v2_has_no_approved_by_flag —` / `THE REGRESSION THAT REINTRODUCES THE SELF-APPROVAL BUG.` This is what the R1 seat-3 draft landed on after reading the actual `tests/test_self_approval_regression.py` file, and it's the canary name from `VERIFICATION.md` line 80. Snake_case in line 1 because it's the function call. ALL CAPS in line 2 because it's the security claim. Both lines under 80 chars. No re-write needed.

3. **The R1 "no voiceover on the close" decision.** Carried over. **I am explicitly NOT adding a voiceover to the close.** The brief allows it ("OPTIONAL," "If you include voiceover, it should be ~25-30 words max for the whole close") and three reasons to omit:
   - Hackathon standard: most award-winning hackathon videos end on the visual. A 2:03 video that ends on a sentence of narration feels like a YouTube outro. A 2:03 video that ends on `GETCUSTODIAN.XYZ` in 64pt white on black feels like a brand mark.
   - The three slides are the message. Slide 1 = what it is. Slide 2 = how to install it. Slide 3 = where to get it. A voiceover would either (a) repeat the slide text (waste of 11s) or (b) add a fourth message that the viewer can't read because they're still reading the slides (waste of attention).
   - The brief itself says: "The final brand mark (URL) is the only thing that matters. If voiceover, keep it to one sentence." I read that as: the brand mark matters more than the sentence. So I'm not adding a sentence.
   - If a reviewer pushes back at the merge step, the only voiceover I would add is one sentence at ~25 words: "Custodian. The kernel between your agents and your money. Pip install, run the verify kit, getcustodian.xyz." (24 words, 9.6s, fits in slide 1 + 2.) But I am recommending against it.

4. **R1's slide 3 timing (4s + 1s tail).** R2 compresses to 3.5s + 0.5s tail because the close is 11s not 13s. The R1 reasoning that the URL is the more-important final beat still holds; I am giving it 3.5s on screen (not 3s) to keep the brand mark readable, plus the 0.5s black tail to land the close. 3.5s + 0.5s = 4.0s for the last slide, which matches R1's allocation even though total close is shorter.

5. **R1's "5 slides → 3 slides" decision.** Carried over. No sponsor slide. No fourth beat. The brief is explicit: "skip the sponsor pitch" in the close. R2 inherits.

6. **Seat 1's hook (0:00–0:18) and seat 2's climax + earn-and-buy + verify_kit (0:18–1:38).** I have not touched them. I have only consumed the handoff — seat 2's last 20s lands at 1:38, which is where my test-count segment starts. The handoff is clean: hard cut from seat 2's `custodian earn-and-buy` final output line to my fresh terminal at 1:38.000.

---

## WHAT I'D WANT TO SEE BEFORE COMMITTING

1. **Voiceover recording needs to happen in the same audio take as the rest of the video.** The brief makes voiceover new in R2. If seat 1 or seat 2 are doing voiceover too, all three seats need a single recording session (or a single re-equalized audio pass in post) so the cadence, mic distance, and room tone match. A patchwork voiceover (mine recorded at the kitchen table, seat 1's at the office) will be audible. **Action: confirm with seats 1 and 2 whether they are adding voiceover to their segments, and if so, schedule a single take.**

2. **The brief's voiceover is 23 words if you count "1,245" as one token. I'm using 26 words because I'm spelling out the number.** This is a defensible call (voiceover cannot be skimmed) but it costs 1.2s of additional airtime (8.8s → 10.4s, still under the 14s budget). If the director wants me to compress, the trim is: "1,245 tests. The one that matters: the self-approval regression — the same bug the verifier just proved couldn't be faked." (22 words, 8.8s). I prefer the spelled-out form. Flagging for the merge.

3. **The pytest run time on recording day.** I am budgeting 14s for the segment. R1 measured 14.20s on a clean cache; cold cache is 16-18s. **Action: dry-run `python3 -m pytest tests/ --tb=no -q` 60 seconds before record and time it.** If >16s, either (a) speed-ramp the middle of the progress dots to 1.2× (preferred — the dots are decorative, not load-bearing), or (b) drop the hold-on-final-line from 1.5s to 1.0s and start the close at 1:51.5 instead of 1:52.0. Don't steal from the close; the close is already at minimum viable.

4. **The 1,245 number will drift.** It's a fact of life. By recording day it might be 1,250 or 1,255. **Action: dry-run pytest the morning of, and if the count changes, edit the test-count caption's first line from `1,245 TESTS.` to the new number. The second line (the regression-test name) is stable across any plausible drift.** If the count jumps by more than 50 tests (i.e., 1,295+), the test-count caption's first line might wrap or look cramped — fall back to a single line `1,295 TESTS PASS — INCLUDING test_spend_v2_has_no_approved_by_flag.` (which is what R1's seat-3 draft anticipated as the fallback).

5. **Slide 3 font size (64pt) is untested at 1920×1080.** R1 flagged this. I'm carrying the 64pt forward because the URL is the final brand mark and it needs to feel like a stamp, not a label. If the editor / director thinks 64pt is too loud, fall back to 48pt. 36pt would be too small. The 0.5s black tail at 2:02.5 is a separate beat and is non-negotiable — it's the visual breath that closes the video.

6. **The voiceover callback ("the same bug the verifier just proved couldn't be faked") depends on seat 2 having run an actual `custodian earn-and-buy` beat that demonstrates the verifier catching a faked self-approval.** If seat 2's earn-and-buy beat does NOT include a "verifier catches the fake" moment, this line is broken — it refers to a thing the audience didn't see. **Action: confirm with seat 2 that their earn-and-buy beat includes a visible "verifier says: CONTRADICTED" output line on a self-approval claim.** If it doesn't, my voiceover needs to change. The fallback phrasing: "the same bug the kernel's regression test catches every time" (15 words, 6.0s) — drops the verifier callout but keeps the regression test claim intact.

7. **The 0.5s black tail (2:02.5 – 2:03.0) is the only "soft" beat in my segment.** R1 had a 1s tail; I'm at 0.5s. 0.5s is enough to register as a beat (the eye sees black and the brain says "end") but not so long that the viewer wonders if the video froze. If it feels too short in review, take 0.3s from slide 3 and give the tail 0.8s.

8. **The deselected-4 count is not in the caption.** It is in the terminal output (`1245 passed, 4 deselected in 14.20s`) but not in the caption. This is correct — the caption's job is the *name* of the regression, not the deselect metadata. The terminal will show it. If a judge asks "what are the 4 deselected?" the answer is ready in R1's draft §"What I'd want to see" item 6 (network tests: Twilio verify, Stripe live API, getcustodian.xyz, and one more). I am not re-investigating that here.

---

## HANDOFF NOTES (for the merge step + recording day)

- **This seat ends at 2:03.000, black.** The video is exactly 2:03 long. No credits, no fade, no logo sting. The black tail is the end.
- **All three slides should be rendered in post (DaVinci Resolve color page → solid color generator + text), not in OBS at record time.** Reason: the on-screen text needs to be 1-frame perfect; a recording-app text source can drift on system load. Render the slides as PNGs at 1920×1080, drop them in on the timeline with a 1-frame cut between them, and the close becomes bulletproof.
- **If slides are rendered as PNGs in post, the font stack must match the in-shot caption font stack** (`SF Mono` / `Cascadia Code` / `Courier New`). Same monospace, same weight. A slide in Helvetica and a caption in Cascadia will be visibly two different videos.
- **The voiceover is 26 words, 10.4s, fits in the 14s test-count window with 3.6s of margin.** The margin is for the visual on the final `1245 passed` line — the voiceover can end and the visual still has time to register the number.
- **One-take recording day.** If pytest is slow on the day, do not re-record voiceover to match — speed-ramp the dots in post instead. Voiceover is the harder thing to re-do; pytest is the easier thing to fix in the edit.
