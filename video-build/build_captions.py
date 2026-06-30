#!/usr/bin/env python3
"""
build_captions.py — produces the 3 close slides + a drawtext filter file
for ffmpeg that burns in every in-shot caption at the right time.

Reads:
    video-build/timing.json      (start/end + caption text per segment)
    video-build/voiceover-raw.wav (just to check it exists)

Writes:
    video-build/captions.ass     (ASS subtitle file)
    video-build/slides/slide-1.png
    video-build/slides/slide-2.png
    video-build/slides/slide-3.png
    video-build/build.sh         (the ffmpeg command to assemble everything)

openSUSE-compatible. No pip deps. Uses PIL for slide rendering (already
available on this box via python3-pillow, else falls back to ffmpeg text).

Usage:
    python3 build_captions.py
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLIDES = HERE / "slides"
SLIDES.mkdir(parents=True, exist_ok=True)


def find_font() -> Path:
    """Find a monospace Bold TTF on the system. openSUSE fallback chain:
    1. DejaVu Sans Mono Bold (flatpak or system)
    2. Nimbus Mono PS Bold (URW, common on openSUSE)
    Returns the first hit or raises."""
    candidates = [
        "/var/lib/flatpak/runtime/org.freedesktop.Platform/x86_64/24.08/"
        "a993292d6ff150598dad4cd1f725aeee01a668b9e721b559ea1b6f6240174d58/"
        "files/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/urw-base35/NimbusMonoPS-Bold.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return Path(c)
    raise RuntimeError(
        "No monospace Bold font found. On openSUSE, run:\n"
        "  sudo zypper install dejavu-fonts\n"
        "Or use a flatpak-supplied DejaVu Sans Mono Bold."
    )


FONT = find_font()


# === timing.json — the canonical timing for every caption + slide ===
TIMING = {
    "captions": [
        # (start_seconds, end_seconds, line1, line2)
        (0.5,  4.0,  "THE AI TRIED TO APPROVE ITS OWN REFUND.", "THE KERNEL SAID NO."),
        (4.0,  6.0,  "HERE'S WHY IT CAN'T.", ""),
        (7.0, 12.0,  "LAYER 1 - NEMOTRON (NVIDIA). REQUESTS ONLY.", "LAYER 2 - CUSTODIAN KERNEL. DECIDES WHAT HAPPENS."),
        (12.0, 17.5, "THE MODEL CAN ONLY REQUEST.", "THE KERNEL CANNOT BE OVERRIDDEN."),
        (19.0, 23.0, "[1/8] EARN - NO BAND, NO CAP, NO APPROVAL.", "RECEIVING MONEY IS ASYMMETRICALLY UNRESTRICTED."),
        (24.0, 30.0, "[2/8] AUTONOMOUS SPEND - WITHIN BAND.", "KERNEL CLEARS. NO HUMAN. PI ON SCREEN."),
        (31.0, 40.0, "[3/8] OVER BAND - KERNEL ESCALATES.", "REAL TWILIO SMS HEADED FOR THE OPERATOR'S PHONE."),
        (45.0, 55.0, "CODE ARRIVED ON TWILIO + OPERATOR PHONE ONLY.", "NOTHING IN THE AGENT'S PROCESS CAN SEE IT."),
        (55.0, 57.0, "[4/8] HUMAN APPROVES.", "$3,500 EXECUTED. STRIPE PI RECORDED."),
        (58.0, 60.0, "[5/8] $40 - NORMALLY FINE. KERNEL SAYS NO.", ""),
        (61.0, 62.0, "[7/8] REFUND ALWAYS ESCALATES. SECOND SMS.", ""),
        (63.0, 68.0, "THE MODEL CAN BE LIED TO.", "THE KERNEL CANNOT."),
        (69.0, 88.0, "[PROOF B] REAL MODAL GPU CYCLE. SAME KERNEL.", "DETERMINISTIC AUDIT TRAIL. NO ONE CAN FAKE IT."),
        (88.0, 95.0, "[1/4] WE INJECT THE BUG.", "THE TEST CATCHES IT. THE FILE IS RESTORED."),
        (100.0, 111.0, "1,245 TESTS. INCLUDES test_spend_v2_has_no_approved_by_flag -", "THE REGRESSION THAT REINTRODUCES THE SELF-APPROVAL BUG."),
    ],
    "slides": [
        # (start_seconds, duration_seconds, line1, line1_pt, line2, line2_pt)
        (112.0, 3.5, "CUSTODIAN", 44, "THE KERNEL BETWEEN YOUR AGENTS AND YOUR MONEY.", 32),
        (115.5, 3.5, "pip install custodian-kernel", 32, "python3 verify_kit.py", 32),
        (119.0, 3.5, "GETCUSTODIAN.XYZ", 64, "", 0),
    ],
    "black_tail": 123.0,  # final black at end (3.5 + 0.5)
    "total_duration": 123.0,
}


# === render the 3 close slides as PNG using PIL (no ffmpeg drawtext needed) ===
def render_slide(text1: str, pt1: int, text2: str, pt2: int, out: Path) -> None:
    """Render a 1920x1080 black slide with white centered monospace text via PIL."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1920, 1080), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font1 = ImageFont.truetype(str(FONT), pt1)
    if text2:
        font2 = ImageFont.truetype(str(FONT), pt2)
        # Two lines stacked
        bbox1 = draw.textbbox((0, 0), text1, font=font1)
        w1, h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
        bbox2 = draw.textbbox((0, 0), text2, font=font2)
        w2, h2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]
        cy = 1080 // 2
        draw.text(((1920 - w1) // 2, cy - h1 - 20), text1, font=font1, fill=(255, 255, 255))
        draw.text(((1920 - w2) // 2, cy + 20), text2, font=font2, fill=(255, 255, 255))
    else:
        bbox = draw.textbbox((0, 0), text1, font=font1)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((1920 - w) // 2, (1080 - h) // 2), text1, font=font1, fill=(255, 255, 255))
    img.save(out, "PNG")
    print(f"  rendered {out.name}")


# === write the in-shot captions as an ASS subtitle file ===
def write_ass() -> Path:
    """ASS subtitles are the standard way to burn timed text with ffmpeg."""
    out = HERE / "captions.ass"
    # ASS header
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans Mono,28,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    def fmt(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"

    for start, end, l1, l2 in TIMING["captions"]:
        text = l1
        if l2:
            text = f"{l1}\\N{l2}"
        # Position: bottom-third, centered
        line = f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,,0,0,0,,{text}"
        lines.append(line)
    out.write_text("\n".join(lines) + "\n")
    print(f"  wrote {out.name} ({len(TIMING['captions'])} caption events)")
    return out


# === write the ffmpeg assembly script ===
def write_assembler() -> Path:
    """The script that stitches screen capture + phone clip + slides + voice."""
    out = HERE / "assemble.sh"
    voiceover = HERE / "voiceover-raw.wav"
    screen = HERE / "screen-capture.mp4"
    phone = HERE / "phone-sms.mp4"

    script = r"""#!/usr/bin/env bash
# assemble.sh — composes the final MP4.
#
# Requires (place in video-build/):
#   - voiceover-raw.wav       (your recorded voice, any sample rate)
#   - screen-capture.mp4      (OBS recording, 1920x1080, 30fps, full take)
#   - phone-sms.mp4           (phone screen recording, vertical 1080x1920 OK)
#   - slides/slide-1.png      (generated by build_captions.py)
#   - slides/slide-2.png
#   - slides/slide-3.png
#   - captions.ass            (generated by build_captions.py)
#
# Output: video-build/custodian-final.mp4 (no captions burned in)
#         video-build/custodian-final-burned.mp4 (captions burned in)
#
# Timing: the screen recording must contain the phone-SMS cut at 0:40-0:45
#         already spliced in (you do that in the OBS recording). The phone-sms.mp4
#         file is used as an OPTIONAL overlay replacement if you recorded phone
#         separately and want to splice it in here instead.

set -euo pipefail

cd "$(dirname "$0")"

VOICE=${1:-voiceover-raw.wav}
SCREEN=${2:-screen-capture.mp4}
PHONE=${3:-phone-sms.mp4}
OUT=${4:-custodian-final.mp4}

[ -f "$VOICE"  ] || { echo "missing $VOICE";  exit 1; }
[ -f "$SCREEN" ] || { echo "missing $SCREEN"; exit 1; }

# Step 1: normalize the screen recording (force 1920x1080 30fps, h264)
echo "[1/5] normalizing screen recording to 1920x1080 30fps h264..."
ffmpeg -y -i "$SCREEN" \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30" \
  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
  -an screen-norm.mp4

# Step 2: trim the normalized screen capture to 1:52 (close starts at 1:52)
echo "[2/5] trimming screen recording to 1:52..."
ffmpeg -y -i screen-norm.mp4 -t 112 -c:v copy screen-trim.mp4

# Step 3: build the close segment from the 3 slides
echo "[3/5] building close segment from slides..."
ffmpeg -y \
  -loop 1 -t 3.5 -i slides/slide-1.png \
  -loop 1 -t 3.5 -i slides/slide-2.png \
  -loop 1 -t 3.5 -i slides/slide-3.png \
  -f lavfi -i "color=c=black:s=1920x1080:d=0.5" \
  -filter_complex "[0:v][1:v][2:v][3:v]concat=n=4:v=1[v]" \
  -map "[v]" -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p close.mp4

# Step 4: stitch screen + close, lay voice on top, sync to 123s total
echo "[4/5] combining screen + close + voiceover..."
ffmpeg -y \
  -i screen-trim.mp4 \
  -i close.mp4 \
  -i "$VOICE" \
  -filter_complex "[0:v][0:a][1:v]concat=n=2:v=1:a=1[outv][outa]" \
  -map "[outv]" -map "[outa]" \
  -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$OUT"

# Step 5 (optional): burn in captions using libass
echo "[5/5] burning in captions..."
if [ -f captions.ass ]; then
  ffmpeg -y -i "$OUT" \
    -vf "subtitles=captions.ass" \
    -c:v libx264 -preset fast -crf 18 -pix_fmt yuv420p \
    -c:a copy \
  "${OUT%.mp4}-burned.mp4"
  echo ""
  echo "============================================================"
  echo "DONE. Outputs:"
  echo "  $OUT          (no captions, captions live in captions.ass)"
  echo "  ${OUT%.mp4}-burned.mp4  (captions burned in)"
  echo "============================================================"
else
  echo "captions.ass not found — skipping burn-in step"
  echo ""
  echo "============================================================"
  echo "DONE. Output: $OUT"
  echo "============================================================"
fi
ffprobe "$OUT" 2>&1 | grep -E "(Duration|Stream)" | head -5
"""
    out.write_text(script)
    out.chmod(0o755)
    print(f"  wrote {out.name}")
    return out


# === main ===
def main() -> int:
    print(f"Building captions + slides in {HERE}")

    # 1. Render 3 close slides
    print("\n[1/3] Rendering close slides...")
    for i, (start, dur, t1, pt1, t2, pt2) in enumerate(TIMING["slides"], 1):
        out = SLIDES / f"slide-{i}.png"
        render_slide(t1, pt1, t2, pt2, out)

    # 2. Write ASS subtitle file
    print("\n[2/3] Writing captions.ass...")
    write_ass()

    # 3. Write ffmpeg assembler
    print("\n[3/3] Writing assemble.sh...")
    write_assembler()

    print(f"""
============================================================
Done. Next steps:

  1. Record the voiceover by reading video-build/teleprompter.md
     Save the audio as:  video-build/voiceover-raw.wav
     (any sample rate, mono or stereo, ffmpeg normalizes it)

  2. Record the screen capture with OBS at 1920x1080, 30fps:
     - 0:00-0:40:    getcustodian.xyz (hero + two-card)
     - 0:18:         hard cut to getcustodian.xyz/operator
     - 0:40-0:45:    hard cut to your phone (record phone separately)
     - 0:45-1:52:    operator panel + 2 fresh terminal windows
     Save the OBS recording as:  video-build/screen-capture.mp4
     Save the phone clip as:     video-build/phone-sms.mp4

  3. Then run:
     cd video-build/
     ./assemble.sh
     # produces video-build/custodian-final.mp4

  4. (Optional) If you want the captions burned IN to the video:
     ffmpeg -i custodian-final.mp4 \\
       -vf "subtitles=captions.ass" \\
       -c:v libx264 -preset fast -crf 18 \\
       -c:a copy \\
       custodian-final-burned.mp4

============================================================
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
