# Video production playbook — reusable for Custodian, Talaria, Paladin

Written while building `custodian-guard-product-v4.mp4` (Codex Guard product
video). This captures the actual working method so the next video — for
Custodian itself, for Talaria, or for Paladin — doesn't start from zero.

## The core idea

Every segment is one of two things:

1. **A real screen recording of an animated HTML page.** Chrome (headless
   desktop, not `--headless=new` screenshot mode) renders the page for real,
   `ffmpeg -f x11grab` records it in real wall-clock time at 1920x1080, and
   that recording becomes the segment's video track. This is how the splash
   logo, the CTA, the live-typed terminal, and the "THE PROBLEM" opener were
   made. Nothing in the frame is faked after the fact — what you see is what
   the browser actually drew, frame by frame, in real time.
2. **A frozen frame from an existing baked slide, animated with a slow
   camera move (Ken Burns).** Used only for content that's already correct
   and expensive to safely regenerate from scratch (the architecture
   diagram, the receipts table, the attack grid, the security-properties
   grid, the closing stakes slide). This is a compromise, not the ideal —
   see "When to retire the Ken Burns segments" below.

A per-segment narration clip (Kokoro TTS) sets the segment's target
duration; every segment is stretched or trimmed to `narration + 0.3s lead +
0.3s tail`. Segments are joined with a 0.35s video crossfade + audio
acrossfade (`concat_xfade_vN.py`).

## Reusable scripts (all in `video-build/`)

| File | Role |
|---|---|
| `capture_html.sh <html> <seconds> <out.mp4>` | Launches Chrome in app mode on a dedicated Xvfb display, records it with x11grab, cleans up. This is the one script every future video reuses as-is. |
| `synth-narration.py` | Reads a `narration-*.json` array of `{id, text}`, synthesizes each line with Kokoro (`am_michael` voice, speed 1.0), writes `narration-audio/<id>.wav`. |
| `build_v4.py` | Per-segment pipeline: extract-or-use-new-clip → optional icon overlay → stretch/trim to target duration → optional Ken Burns camera → mux with padded narration audio → `<id>_final.mp4`. Segment list + camera choice lives at the top of this file — copy it, don't generalize it prematurely. |
| `concat_xfade_v4.py` | Reads `segments.json` (written by the build script), chains everything with `xfade`/`acrossfade`. |

For a new video (Custodian, Talaria, Paladin): copy `build_v4.py` and
`concat_xfade_v4.py`, change the segment list and the `VB`/`WORK`/`OUT`
paths. Everything else — `capture_html.sh`, the narration synth step, the
xfade logic — is drop-in reusable.

## Design system established so far

- **Palette:** near-black bg `#060604`, amber accent `#ffb000`, teal/green
  accent `#2ee6a6`, danger red `#ff4d4d`, body text `#e8e8ee` / muted gray
  `rgba(255,255,255,0.5-0.55)`.
- **Fonts:** `DejaVu Sans` (headlines, bold), `DejaVu Sans Mono` (code,
  terminal, labels). Deliberately *not* a Google Font (`JetBrains Mono` was
  tried first) — headless Chrome has no network guarantee in this
  environment, and a missing web font silently falls back to a generic
  serif, which is worse than picking a system font that's guaranteed
  present. Check with `fc-list | grep -i <name>` before using any font.
- **Background texture:** a faint rotated perspective grid
  (`perspective(700px)` + `rotateX(±78deg)`) plus one or two radial glows
  positioned to match the accent color in play. Reused verbatim across
  splash/CTA/terminal/problem cards — this repetition is what makes them
  read as one system instead of four unrelated slides.
- **Motion vocabulary (the "camera" concept):** don't use one animation
  style for everything. Three named treatments in `build_v4.py`'s `CAMERAS`
  dict:
  - `zoomin-calm` (max 1.03x) — for information-dense slides where the
    viewer needs to read comfortably. "Useful."
  - `zoomin-strong` (max 1.05x) — for a single emotional/closing beat.
    "Attractive." Don't use it more than once or twice per video or it
    stops reading as emphasis.
  - `zoomout` (starts 1.05x, settles to 1.0x/full-frame) — for the
    widest/most content-dense slides. Doubles as a safety choice: since it
    *ends* at zero crop, it can't clip anything by the time the viewer has
    finished reading. Used here for the two slides that came closest to
    (and in one case did) clip text.
  - Fully custom HTML animation — reserved for the highest-visibility
    moments (opener, closer, and anything with dramatic/narrative content
    like "THE PROBLEM"). Most expensive to build, biggest visual payoff.

## Known pitfalls (all hit for real this session — check these first)

1. **`zoompan` defaults to a top-left anchor, not centered.** Without
   explicit `x`/`y` expressions, "zooming in" crops progressively more off
   the *right and bottom* only, while the top-left stays fixed. On a
   16:9 slide with right-aligned or bottom-anchored text, this *will*
   eventually clip it — confirmed on this project's security-properties
   slide, whose bottom tagline was cut off. Always set
   `x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'` to zoom into the center.
2. **`-ss` before `-i` resets PTS near 0** and breaks any filter (like a
   burned-in ASS overlay) that depends on the original absolute timeline.
   `-ss` *after* `-i` preserves it. Costs nothing to always put `-ss` after
   `-i` when a filter's timing matters.
3. **A still-frame grab (`-sseof -0.1`) can land just outside a prior
   fix's active time window.** If an earlier ASS-overlay caption fix was
   scoped to `72.20–90.80s` of a source video, and a later pipeline
   extracts `71.2s` for `20.0s` (ending at `91.2s`), the Ken-Burns still
   frame — grabbed from the very end of that window — lands 0.4s *after*
   the fix's cutoff and silently reverts to the original, wrong caption.
   Always check the still-frame's actual source timestamp against any
   known fix windows before trusting a re-extraction.
4. **TTS reads a decimal mid-sentence as a sentence break.** Kokoro
   (and likely most TTS engines) read "GPT-5.6" as "GPT five... [long
   pause]... six" — audibly wrong. Spell numbers out in the narration text
   ("GPT five point six"); verify with `ffmpeg -af silencedetect` on the
   candidate phrasing before committing (compare gap durations, don't just
   read the text and guess).
5. **Headless Chrome's `--no-sandbox` triggers a visible warning infobar**
   that eats the top ~40px of the capture. Not needed when running as a
   non-root user — just omit the flag.
6. **Google Fonts / any network font will silently fail in this sandbox.**
   Confirm the font is actually installed (`fc-list`) before referencing it
   in an HTML card; otherwise it silently falls back to a generic font and
   nobody notices until a pixel-level review.
7. **`ffmpeg -frames:v 1 out.png` fails on plain filenames** — needs
   `-update 1` for single-frame PNG output, or a `%03d`-style pattern.
8. **Multiple concurrent Claude Code sessions can share this filesystem.**
   Check `ps aux` and file mtimes before overwriting anything in
   `video-build/` — a previous session's in-progress asset (e.g. an overlay
   PNG referenced from a script but not committed anywhere durable) may
   only exist in *that session's own* scratchpad directory, not this one.

## When to retire the Ken Burns segments

The zoomed-static-frame segments (`s3`, `s4`, `s6`, `s7`, `s8` as of v4) are
a compromise: they're frozen frames baked into an earlier video with no
separately editable source, so redesigning them risks silently
reintroducing factual errors (this already happened once — see pitfall #3).
The real fix, next time there's budget for it, is to rebuild each of those
as its own HTML card (matching the design system above) so every segment in
the video is a real capture, none of them a static crop. That also removes
the Ken-Burns-vs-fix-window fragility entirely.

## For the next video (Custodian / Talaria / Paladin)

- Reuse `capture_html.sh` unchanged.
- Reuse the palette/font/background-texture system unchanged — that's what
  makes separate videos about separate products still feel like one brand.
- Do **not** reuse specific slide content — re-derive facts (test counts,
  CLI commands, package names) from that product's actual current README/
  code at build time, the same way this project's narration was checked
  against real script output rather than assumed.
- Vary the motion vocabulary per video's own emotional arc, but keep the
  three-tier naming convention (`zoomin-calm` / `zoomin-strong` / `zoomout`)
  so future-you doesn't have to reverse-engineer intent from raw numbers.
- Start the fact-finding the same way this session did: read the product's
  real README, run its real demo/verify commands, capture real output —
  never write narration or on-screen text from memory of what a product
  "probably" does.
