#!/usr/bin/env python3
"""
build_captions.py — produces the 3 close slides + ASS subtitle file.

Reads:
    video-build/timing.json      (canonical timing for captions + slides)

Writes:
    video-build/captions.ass     (ASS subtitle file)
    video-build/slides/slide-1.png
    video-build/slides/slide-2.png
    video-build/slides/slide-3.png

Usage:
    python3 build_captions.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SLIDES = HERE / "slides"
SLIDES.mkdir(parents=True, exist_ok=True)


def find_font() -> Path:
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


def load_timing() -> dict:
    path = HERE / "timing.json"
    with open(path) as f:
        return json.load(f)


def render_slide(text1: str, pt1: int, text2: str, pt2: int, out: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1920, 1080), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font1 = ImageFont.truetype(str(FONT), pt1)
    if text2:
        font2 = ImageFont.truetype(str(FONT), pt2)
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


def write_ass(timing: dict) -> Path:
    out = HERE / "captions.ass"
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

    for start, end, l1, l2 in timing["captions"]:
        text = l1
        if l2:
            text = f"{l1}\\N{l2}"
        line = f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,,0,0,0,,{text}"
        lines.append(line)
    out.write_text("\n".join(lines) + "\n")
    print(f"  wrote {out.name} ({len(timing['captions'])} caption events)")
    return out


def main() -> int:
    print(f"Building captions + slides in {HERE}")

    timing = load_timing()

    print("\n[1/3] Rendering close slides...")
    for i, (start, dur, t1, pt1, t2, pt2) in enumerate(timing["slides"], 1):
        out = SLIDES / f"slide-{i}.png"
        render_slide(t1, pt1, t2, pt2, out)

    print("\n[2/3] Writing captions.ass...")
    write_ass(timing)

    dur = timing["total_duration"]
    cap_count = len(timing["captions"])
    print(f"\nSummary: {dur}s total duration, {cap_count} caption events")

    return 0


if __name__ == "__main__":
    sys.exit(main())
