# Seat 1: HOOK + ARCHITECTURE (0:00–0:18)
**Author:** minimax-m3 | **Date:** 2026-06-29 | **Scope:** [0:00–0:18] of the 1:45 final script

This seat owns the first 18 seconds. The phone-SMS climax lives at 0:40–0:55 (Seat 2) and the verify_kit bug-reintroduction beat lives at 1:18–1:32 (Seat 3). My job is to land the judge in the chair for the first 6 seconds and then show the two-layer model in 12 seconds of pure visual.

---

## [0:00–0:06] HOOK (6 seconds flat)

**On-screen content (exact):**
- Browser full screen, no chrome visible.
- URL bar: `https://getcustodian.xyz/`
- Frame visible at 0:00: the hero section already loaded.
  - Top eyebrow row (visible): `⬡ DGX Spark GB10 · 🛡 NemoClaw · ◉ Nemotron Super 120B · ◆ Hermes · stripe`
  - Headline (centered, ~80pt white): "Let AI handle refunds, spend, and purchasing." / "Without the risk."
  - The two-card visual is JUST below the fold — not visible at 0:00. This is correct; the architecture beat brings it up.
- No scroll. No click. No cursor motion.
- Black 4K background of the page; nothing else moves.

**Caption #1 (appears at 0:00.5, holds 0:00.5–0:04.0):**
```
THE AI TRIED TO APPROVE ITS OWN REFUND.
THE KERNEL SAID NO.
```
- Position: bottom-third, white text, monospace 28pt, transparent black bar (~60% opacity). 2 lines, both under 60 chars.
- Lower-third is correct here because the headline is center-top and won't fight the caption.

**Action (0:00–0:04):** Hold still. No cursor. No click. Static frame. The contrast between the still screen and the bold caption is the entire point — the product is calm because the kernel is working.

**Caption #2 (appears at 0:04.0, holds 0:04.0–0:06.0):**
```
HERE'S WHY IT CAN'T.
```
- 1 line, same style. 17 chars — the shortest caption of the video, which is what makes the cut feel like a snap.

**Action (0:04–0:06):** Still hold. Caption #2 sits for 2 full seconds — this is the visual breath before the architecture cut.

**Cut to architecture at 0:06.0.** Hard cut. No fade. (Per all prior scripts — this is non-negotiable; the cut is the punctuation.)

---

## [0:06–0:18] ARCHITECTURE (12 seconds)

**On-screen content (exact):**
- The same browser tab — **do not switch tabs, do not navigate away**.
- **Scroll DOWN ~1 viewport (≈ 700px) at a steady rate over 3.5 seconds.**
- Target frame at 0:09.5 (the held frame for caption #1): the **two-card metaphor** in the hero.
  - Left card: `HERMES AGENT` / `Nemotron Super 120B` / `ROLE: REQUESTS ONLY` (dark card, REQUESTS ONLY in amber)
  - Right card: `NEMOCLAW KERNEL` / `Custodian Authority` / `PER-ACTION CAP: $250` (amber-bordered card, $250 in amber)
  - A literal `+` between them, reinforcing "agent AND kernel, not agent OR kernel."
- This visual already exists at `getcustodian.xyz` in `pages-frontend/index.html` lines 329–349. Verified by reading the file: `<div class="card-metaphor">` with `cc cc-employee` and `cc cc-company` siblings, plus a `cc-vs` "+" between them. The "$250" cap is hard-coded in the markup, not a live value, so it will display correctly during recording without any backend state.

**Caption #1 (appears at 0:07.0 as the two cards come into view, holds 0:07.0–0:12.0):**
```
LAYER 1 — NEMOTRON (NVIDIA). REQUESTS ONLY.
LAYER 2 — CUSTODIAN KERNEL. DECIDES WHAT HAPPENS.
```
- 2 lines, both under 70 chars. Monospace 28pt, white on transparent black, bottom-third.
- This is a verbatim match to the existing screen-only script's framing, with one wording fix (see "What I am NOT deferring to" below).
- Note: `docs/WHAT_THIS_IS.md` (the project's authoritative mental-model doc) defines Layer 1 = Custodian engine and Layer 2 = agent. I am deliberately flipping the numbering to match what the audience sees — *Nemotron first* — and matching the existing screen-only script. The visual two-card metaphor in the hero leads with "HERMES AGENT" on the left; number 1 should be on the left.

**Action (0:07.0–0:12.0):**
- Cursor moves from off-screen onto the LEFT card (HERMES AGENT). 1.0s ease-in move. Hold on the card for 1.5s. This is the "requestor" hand-point.
- Then cursor moves RIGHT across the `+` to the NEMOCLAW KERNEL card. 0.5s move. Hold for 1.5s. This is the "decider" hand-point.
- Cursor stays visible the entire time — the existing screen-only script is explicit that "the cursor is the human presence" and I agree.

**Caption #2 (appears at 0:12.0, holds 0:12.0–0:17.5):**
```
THE MODEL CAN ONLY REQUEST.
THE KERNEL CANNOT BE OVERRIDDEN.
```
- 2 lines, both under 45 chars. Same style.
- This is the structural claim. The two cards have done the visual work; the caption locks in the *property*, not the feature list.

**Action (0:12.0–0:17.5):** Hold still on the two cards. No further cursor motion. The static hold reads as confidence — the kernel is not arguing with itself.

**Cut to Seat 2's domain (operator panel) at 0:18.0.** Hard cut. From this point the operator panel takes over.

---

## Why this version, point by point

1. **Hook holds still.** All four existing scripts (screen-only, director's, 1m45, FINAL, 90s) put a static browser frame on screen during the hook. I keep that. The judge needs ~2 seconds to read "THE AI TRIED TO APPROVE ITS OWN REFUND" before the second line lands; a moving frame fights the read. The 6-second budget is unforgiving — 2 captions in 6 seconds is the max that reads cleanly.

2. **I use the existing two-card visual, not the 3-stage pipeline.** The landing page has *two* architecture visuals: the two-card metaphor (visible at scroll-1 from top) and a 3-stage pipeline diagram (`.pipe` with `.stage.s1` AI Judgment / `.stage.s2` Verifier / `.stage.s3` Kernel, deeper in the page, lines 569–596 of `index.html`). I deliberately use the two-card. Reason: in 12 seconds, two boxes read in under a second; three boxes + the verifier in the middle adds a concept ("wait, the verifier is a third thing?") that the 1:45 budget cannot pay off. The Verifier is a later beat in Seat 2/3's domain; the hook architecture segment should be the *cleanest possible* two-layer model, and that visual already exists on the page.

3. **The architecture segment shows two cards, not a diagram-with-arrows.** The visual literally is "card + card with a + between them." That is the two-layer model in one glance. I do not need to draw arrows — the `+` glyph in the markup is the boundary marker.

4. **I keep the cursor on both cards.** The cursor moving from the agent card to the kernel card is the *kinetic* version of "model proposes, kernel decides." Director's script and screen-only script both endorse this. I time the move to coincide with the caption handoff, so the visual hand-point reinforces the verbal claim.

5. **All claims are factually checkable from the repo:**
   - The two-card metaphor exists at `pages-frontend/index.html` lines 329–349. Verified by reading the file. The `+` glyph is in `<div class="cc-vs">+</div>`. The PER-ACTION CAP is hard-coded `$250` in the markup.
   - The fact that refunds always escalate is in `docs/ARCHITECTURE.md` line 222 and `pages-frontend/operator.html` line 213 ("Refunds always escalate — no autonomous refund path by design").
   - The fact that the kernel can be overridden only by an operator is in `docs/ARCHITECTURE.md` line 224 ("Never bypass kill switch, approval gate, or dead-man's-switch under any pressure").
   - I do NOT claim "OS-level" anywhere in the visible captions — the kernel is userspace Python with a remote-first enforcement pattern (DGX Spark → argobox-lite local fallback, per `docs/ARCHITECTURE.md` lines 88–101). The two-card visual's "NemoClaw" label is a marketing wrapper, not a technical claim in the captions, so this stays honest.

6. **The 6-second hook is short on purpose.** Seat 2's climax is at 0:40. That means Seat 2 needs the judge still watching 40 seconds in. The hook cannot borrow from the climax — the climax must be a *discovery*, not something promised in the first 6 seconds. The hook's only job is to be a sharp tension-setter: "the AI tried X, the kernel said no, watch me prove it."

---

## What I am NOT deferring to (and why)

| Prior script | What it said about [0:00–0:18] | What I'm doing instead | Why I'm not deferring |
|---|---|---|---|
| `docs/VIDEO-SCRIPT.md` (2:05, with face) | On-camera presenter, 8-second hook with voiceover, 17-second problem framing, 15-second architecture with VO over pipeline rail | Hold-static 6s, scroll 12s, no presenter | Wrong format (face/voice) and wrong timing (8s hook + 17s problem = 25s of warm-up eats Seat 2's climax budget). Rejecting whole premise. |
| `docs/VIDEO-SCRIPT-SCREEN-ONLY.md` (1:45 preferred) | 8-second hook with `getcustodian.xyz` static + 2 captions; 17-second architecture with scroll to pipeline diagram + 2 captions | 6-second hook + 12-second architecture | I'm 2 seconds shorter on hook and 5 seconds shorter on architecture. The reason: the screen-only script puts the operator panel first click at 0:25, which leaves Seat 2 with only 15 seconds of breathing room before the 0:40 climax — too tight. My version hands Seat 2 a hard handoff at 0:18 with 22 seconds of room. **Net: same total length, more time for the climax.** |
| `docs/VIDEO-DIRECTOR-SCRIPT.md` (1:45) | 6s hook on `getcustodian.xyz` + 12s architecture scrolling to pipeline diagram at `localhost:8094/operator` | 6s hook + 12s architecture scrolling the **landing page two-card visual** | The director's script tells Hermes to navigate to `localhost:8094/operator` for the architecture segment. That moves the architectural claim to *behind localhost*, which is a worse artifact for the judge clip. The landing page two-card is the public-facing version of the same claim; using it keeps the judge clip shareable. I'm taking the director's TIMING (6 + 12) but the screen-only script's STAYING ON PUBLIC URL. |
| `docs/VIDEO-SCRIPT-1m45.md` (1:45, with face) | 8s on-camera hook + 17s on-camera problem + 15s VO-over-pipeline architecture | Same rejection as the 2:05 version — wrong format. | Rejecting whole premise (face/voice). |
| `docs/VIDEO-SCRIPT-FINAL.md` (90s) | 10s black-screen text-fade hook + 15s problem split + 15s demo-verify solution + 25s verify_kit proof + 15s architecture + 10s CTA | None of it | Different structure entirely: this 90s script front-loads the demo-verify and puts architecture at 1:05. Doesn't fit the 1:45 architecture-first build. |
| `docs/VIDEO_SCRIPT.md` (90s) | Hook = terminal running `verify_kit.py` showing CONTRADICTED in red | None | This is the "lead with the proof" variant. It does the climax-then-explain structure. Doesn't match the agreed-upon architecture-first build. |

**The one prior-script detail I AM preserving:** the exact caption text "THE AI TRIED TO APPROVE ITS OWN REFUND. / THE KERNEL SAID NO." This line is the strongest caption in any of the six scripts — short, factually true, and it telegraphs the climax without giving it away. It is verbatim from `VIDEO-SCRIPT-SCREEN-ONLY.md` and `VIDEO-DIRECTOR-SCRIPT.md`.

---

## What I'd want to see before committing

1. **The landing page must be the deployed version on recording day.** The two-card visual is in `pages-frontend/index.html` (committed), but the live URL is served via `pages-frontend/` deploy to Cloudflare. The director's script and existing screen-only script both imply `getcustodian.xyz` is reachable. If on recording day the deploy is stale, the `$250` per-action cap might be a different number, or the cards might not render. **Mitigation:** open `getcustodian.xyz` in the recording browser 60 seconds before the take and confirm the two-card metaphor is at the expected scroll position. If it's drifted, fall back to the deeper 3-stage `.pipe` diagram (also in `index.html` lines 569–596) — but that requires a longer scroll and more careful caption timing, so prefer the two-card.

2. **Test-count claim for Seat 3.** I am not responsible for the [1:18–1:32] segment, but I am flagging this for Seat 3 to verify on recording day: the existing scripts cite **1,239** (director's, 1m45), **1,254** (screen-only), and **1,176** (90s final) — three different numbers. As of 2026-06-29, `python3 -m pytest tests/ --collect-only -q` reports **1245 collected, 4 deselected**. The active test count is **1,245**. Seat 3 should use this number on the day, not any of the three prior numbers. (The screen-only script's "1,254" is plausible if `dashboard/tests/` is also counted, since `verify_kit.py` line 55 runs both `tests/` and `dashboard/tests/`. Worth confirming which set the final video should display.)

3. **"OS-level" framing.** The landing page's own lede says "the OS enforces them" and the page also uses "kernel sandbox (NemoClaw)" and "NemoClaw kernel sandbox." The actual implementation per `docs/ARCHITECTURE.md` is a remote-first pattern where DGX Spark (a Linux box) runs `enforce_server.py` with a 1s timeout, falling back to local in-process enforcement. The "OS" in the marketing is the *operator's* OS, not a kernel module. **My captions do not say "OS-level" anywhere**, so this is safe for my segment. But Seat 1+Seat 3 should agree on a single framing in the closing slides — using "kernel-enforced" instead of "OS-enforced" is the safer technical phrasing. Flagging because the existing scripts mix the two.

4. **"Two layers" vs "three layers" framing.** `docs/WHAT_THIS_IS.md` is explicit: "two genuinely different things in this system." The landing page's `.pipe` diagram shows three (AI / Verifier / Kernel). The 1:45 budget cannot reconcile this in 12 seconds. I'm going with **two** for the hook architecture segment and trusting Seat 2/3 to introduce the verifier later. If the seat-3 closer wants to bring back the three-stage frame, that's fine; just don't re-introduce it at 0:06–0:18.

5. **The 1-second caption hold at 0:12.0–0:13.0 may feel too long for some viewers.** The "THE MODEL CAN ONLY REQUEST / THE KERNEL CANNOT BE OVERRIDDEN" caption is the structural claim. If on review it feels too long, the cut to Seat 2 can move to 0:17.0 (1.5s of hold instead of 0.5s) and Seat 2's first beat gets 1 second more. I prefer 2.5s of caption hold; a judge reading at 250 wpm needs ~1.8s for 2 lines.

6. **No music, no audio.** All six prior scripts agree: silent, captioned, no music. Confirmed in my segment.

---

## Handoff to Seat 2

At 0:18.0, hard cut to `https://getcustodian.xyz/operator` (or `localhost:8094/operator` if recording on the backend host — the director's script has both; confirm before recording). The operator panel should be scrolled to Step 0 (Earn $1,200) before the cut so Seat 2's first click is the only motion in the first 2 seconds of their segment. Captions go silent for ~0.5s after the cut to let the eye reset.
