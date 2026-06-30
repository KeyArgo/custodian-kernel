# CUSTODIAN — Video Build Kit
**Hackathon:** NVIDIA × Stripe × Nous Research Hermes Agent Hackathon
**Length:** 2:03 (123 seconds)
**Format:** Screen-only recording + voiceover. No face. No music.

This directory has everything you need to record and assemble the video
on openSUSE. Tools used: `ffmpeg`, Python 3 (stdlib + PIL), no other
dependencies.

---

## What you record

| File | Source | How |
|---|---|---|
| `voiceover-raw.wav` | You | Read `teleprompter.md` in a quiet room, single take |
| `screen-capture.mp4` | OBS | 1920×1080, 30fps, full take through the script |
| `phone-sms.mp4` | Phone | Record the 5s SMS arrival separately, vertical OK |

## What the scripts do

| File | Purpose |
|---|---|
| `teleprompter.md` | The voiceover text with timing and pause markers |
| `build_captions.py` | Renders the 3 close slides, writes ASS caption file, writes ffmpeg assembler |
| `assemble.sh` | Normalizes screen recording, splices in close slides, lays voice, burns captions |
| `captions.ass` | (Generated) In-shot captions with timing, ready to burn in |
| `slides/slide-{1,2,3}.png` | (Generated) The 3 black slides for the close |
| `custodian-final.mp4` | (Output) Final video, captions not burned in |
| `custodian-final-burned.mp4` | (Output) Final video, captions burned in via libass |

---

## Step-by-step (openSUSE, 30 minutes total)

### 1. Generate the slides and caption file (1 minute)

```bash
cd /mnt/homes/galileo/argo/Development/hermes-hackathon-2026/video-build
python3 build_captions.py
```

Output: `slides/slide-{1,2,3}.png`, `captions.ass`, `assemble.sh`.

### 2. Record the voiceover (10 minutes)

Print `teleprompter.md` or load it on a separate device. Read each block
in order. Keep the `[pause]` tags as ~0.3–0.5s of silence. The `[silence]`
tags are dead air between segments — don't speak during them.

Record as a single WAV file, any sample rate (ffmpeg normalizes):

```bash
# On openSUSE, the default audio recorder is GNOME Sound Recorder or
# PulseAudio's parec. Use whatever you prefer. Save as:
mv ~/recordings/voice.wav video-build/voiceover-raw.wav
```

Verify it sounds OK:

```bash
ffplay -autoexit video-build/voiceover-raw.wav
```

If the pacing is off (too fast, too slow, awkward pauses), re-record.

### 3. Record the screen capture (5 minutes)

Open OBS at 1920×1080, 30fps. Start recording. Follow the script in
`/mnt/homes/galileo/argo/Development/hermes-hackathon-2026/docs/VIDEO-SCRIPT-FINAL.md`.

Key points:
- 0:00–0:18: Browser at `https://getcustodian.xyz/`, scroll to two-card metaphor
- 0:18: Hard cut to `https://getcustodian.xyz/operator`, scrolled to Step 0
- 0:18–0:40: Click Step 0, Step 1, Step 2. The phone-SMS cut at 0:40 is
  the climax — record the phone separately as `phone-sms.mp4` and
  splice it in during the OBS recording (or in post via the assembler)
- 0:45–1:52: Steps 3-7 on the operator panel, then two fresh terminal windows
  for `custodian demo-verify` (1:02-1:08), `custodian earn-and-buy` (1:08-1:28),
  `python3 verify_kit.py` (1:28-1:38), `python3 -m pytest tests/ --tb=no -q` (1:38-1:52)

Save the OBS recording as:

```bash
mv ~/Videos/obs-recording.mp4 video-build/screen-capture.mp4
```

**Pre-record checks (mandatory):**
- `echo $MODAL_TOKEN_ID` returns `ak-...` (NOT empty — if empty the earn-and-buy beat prints the fallback string)
- `python3 -m pytest tests/ --tb=no -q` returns `1245 passed` (or update the caption)
- `custodian earn-and-buy` once as dry run, confirm `Elapsed: Xs | GFLOPs: Y | Billed: $Z` (NOT the fallback)

### 4. Assemble the final video (5 minutes)

```bash
cd video-build
./assemble.sh
```

Output: `video-build/custodian-final.mp4` (captions not burned) and
`video-build/custodian-final-burned.mp4` (captions burned in via libass).

### 5. Review

Watch the output. If timing is off (pytest ran slow, voice pacing
mismatched video events), fix in post:

```bash
# Trim 2s from the close
ffmpeg -i custodian-final.mp4 -t 121 -c copy custodian-final-trimmed.mp4

# Re-burn captions
ffmpeg -i custodian-final-trimmed.mp4 \
  -vf "subtitles=captions.ass" \
  -c:v libx264 -preset fast -crf 18 \
  -c:a copy \
  custodian-final-trimmed-burned.mp4
```

### 6. Export for upload

```bash
ffmpeg -i custodian-final-burned.mp4 \
  -c:v libx264 -preset slow -crf 20 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  custodian-hermes-hackathon-2026.mp4

# Verify file size is under 100MB
ls -la custodian-hermes-hackathon-2026.mp4
```

---

## If the openSUSE box doesn't have PIL or PIL is missing

```bash
sudo zypper install python3-pillow
# or, if zypper refresh is slow:
pip3 install --user Pillow
```

## If the openSUSE box has a different ffmpeg with no libass support

```bash
ffmpeg -codecs 2>/dev/null | grep ass
# if empty, the captions.ass burn-in step will fail. Workaround:
# upload custodian-final.mp4 (no captions) to YouTube and add captions
# via YouTube's CC editor, or hardcode them in OBS during recording.
```

## If the screen recording is the wrong resolution

The assembler's first step normalizes to 1920x1080. If the video looks
stretched or squished, change the `scale=` filter in `assemble.sh`:

```bash
-vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30"
#                ^^^^^^^^^^ keep aspect, ^^^^^^^^^ pad with black to hit 1920x1080
```

For 16:9 source, no padding shows. For 4:3 or vertical phone video, padding
fills the bars.
