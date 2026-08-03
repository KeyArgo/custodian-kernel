# Video build template — start here for the next Custodian/Talaria/Paladin video

This folder is the reusable skeleton distilled from building
`custodian-guard-product-v4.mp4` (see
`/home/dev/custodian-dev/video-build/PIPELINE-PLAYBOOK.md` for the full
narrative writeup and worked example). That folder stays as the Codex Guard
video's own archive — do not build new videos inside it. This folder is
the clean starting point instead.

## Step 0 — copy this folder, don't edit it in place

```bash
cp -r /home/dev/custodian-dev/video-build-template /home/dev/custodian-dev/video-build-<product>
cd /home/dev/custodian-dev/video-build-<product>
```

Every future video (Talaria, Paladin, Custodian-itself, etc.) gets its own
`video-build-<product>/` copy. This template folder should stay generic and
untouched so it's still clean for whichever video comes after that one.

## Step 1 — re-derive the facts, don't reuse old slide content

Before writing a single word of narration: read that product's actual
current README, run its actual demo/verify commands, capture the actual
output. Never write on-screen text or narration from memory of what the
product "probably" does or from a prior video's script — a stale test
count or CLI command is exactly the kind of error this pipeline has already
caught and fixed more than once. This is the single most important rule in
this whole template; everything else below is just plumbing.

## Step 2 — write your narration script

Create `narration-<product>.json` in your new folder — an array of
`{"id": ..., "text": ...}` objects, one per segment. `id` becomes the
filename stem for that segment's audio and its `NEW_CLIPS`/`segments` key
in `build_template.py`.

Watch for: Kokoro (the TTS engine) reads a decimal mid-sentence as a
sentence break — "GPT-5.6" gets read as "GPT five... [pause]... six".
Spell numbers out in the narration text ("GPT five point six").

Synthesize it:

```bash
python synth-narration.py narration-<product>.json narration-audio
```

This sets each segment's target duration (used in Step 4) — narration
length + 0.3s lead + 0.3s tail, baked into `build_template.py`.

## Step 3 — build your HTML cards, capture them

For each segment that's a fresh animated card (the common case — prefer
this over reusing an old baked frame, see `PIPELINE-PLAYBOOK.md`'s "When to
retire the Ken Burns segments"):

1. Copy `card-template.html` to `<segment-id>.html` and edit the content
   inside `.container` — leave the palette/background/font system alone.
2. Capture it:
   ```bash
   ./capture_html.sh <segment-id>.html <duration_seconds> <segment-id>-rendered.mp4
   ```
   Duration should roughly match that segment's narration length from
   Step 2 (`build_template.py` will stretch/trim slightly to match exactly).

For segments that reuse a frozen frame from an existing baked video
instead (the Ken-Burns compromise pattern) — only do this if there's a
real prior asset worth salvaging and no separately-editable source; it's a
concession, not the default. Set `FIXED` in `build_template.py`'s CONFIG
block and use `kind="extract"` for that segment.

## Step 4 — edit and run the build script

Edit the `CONFIG` block at the top of `build_template.py`:

- `segments` — your real segment list, one tuple per segment, matching the
  narration ids from Step 2.
- `NEW_CLIPS` — map each `kind="new"` segment name to its rendered mp4 from
  Step 3.
- `FIXED` — only if you have `kind="extract"` segments (see Step 3).
- Pick a `camera` per segment from `CAMERAS` (`zoomin-calm`, `zoomin-strong`,
  `zoomout`, or `None`) — vary it across the video's own emotional arc, but
  keep these three names rather than inventing new ones, so a future video's
  builder doesn't have to reverse-engineer intent from raw numbers. Use
  `zoomin-strong` at most once or twice per video — it's for a single
  standout beat, not a default choice.

Then:

```bash
python build_template.py
```

Writes `work/<id>_final.mp4` per segment and `work/segments.json` (read by
the next step).

## Step 5 — assemble

Edit `OUT` at the top of `concat_xfade_template.py` to your video's real
output filename, then:

```bash
python concat_xfade_template.py
```

Chains all segments with a 0.35s video crossfade + audio acrossfade.

## Known pitfalls — check these before you hit them again

All of these were hit for real building the Codex Guard video. Full detail
in `/home/dev/custodian-dev/video-build/PIPELINE-PLAYBOOK.md`; short version:

1. **`zoompan` defaults to a top-left anchor.** `build_template.py`'s
   `CAMERAS` dict already centers correctly (`ZX`/`ZY` expressions) — don't
   remove them even if a segment "looks fine" without checking all four
   corners at max zoom.
2. **`-ss` before `-i` resets the timeline**, breaking any filter that
   depends on absolute source time. Put `-ss` after `-i` whenever a filter's
   timing matters.
3. **A still-frame grab can land just outside a prior fix's active time
   window** if you're re-extracting from an old baked video. Always check
   the still's actual source timestamp against any known fix windows before
   trusting it.
4. **TTS reads a decimal as a sentence break.** Spell numbers out in
   narration text; verify with `ffmpeg -af silencedetect` on the candidate
   phrasing if you're unsure, don't just eyeball the text.
5. **Headless Chrome's `--no-sandbox` shows a visible infobar** that eats
   the top ~40px of the capture. Don't add that flag — it's not needed
   running as a non-root user, and `capture_html.sh` already omits it.
6. **Google Fonts / any network font silently fails** in this sandbox.
   Run `fc-list | grep -i <name>` before referencing any font that isn't
   already in `card-template.html`.
7. **`ffmpeg -frames:v 1 out.png` needs `-update 1`** for a plain (non
   `%03d`-pattern) filename — already included in `build_template.py`'s
   still-frame grab.
8. **Multiple concurrent sessions can share this filesystem.** Check
   `ps aux` and file mtimes before overwriting anything, especially in a
   shared scratch dir.

## What to reuse unchanged vs. what to edit per video

| Reuse as-is | Edit per video |
|---|---|
| `capture_html.sh` | `card-template.html` → your segment HTML |
| Palette/font/background CSS in `card-template.html` | on-screen content, narration text |
| `synth-narration.py` | `narration-<product>.json` |
| Pipeline logic in `build_template.py` (below the CONFIG block) | the CONFIG block itself |
| `concat_xfade_template.py`'s xfade logic | `OUT` filename at the top |
| The `CAMERAS` naming convention | which camera each segment uses |
