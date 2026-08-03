#!/usr/bin/env python3
"""Chain the 9 v3 segments with video xfade + audio acrossfade transitions."""
import subprocess, json, sys

WORK = "/tmp/claude-1002/-home-dev/3d9d4a9c-5252-4847-8455-775de9725d9b/scratchpad/build-v3"
OUT = "/home/dev/custodian-dev/video-build/custodian-guard-product-v3.mp4"
XF = 0.35  # crossfade duration in seconds

def probe_dur(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                         "-of","default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(r.stdout.strip())

segments = json.load(open(f"{WORK}/segments.json"))
paths = [p for _, p, _ in segments]
durs = [probe_dur(p) for p in paths]
n = len(paths)

inputs = []
for p in paths:
    inputs += ["-i", p]

filt = []
for i in range(n):
    filt.append(f"[{i}:v]fps=25,format=yuv420p,settb=AVTB[nv{i}]")
    filt.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=mono,asettb=AVTB[na{i}]")

prev_v = "nv0"
prev_a = "na0"
cum = durs[0]
for i in range(1, n):
    offset = cum - XF
    vout = f"v{i}"
    aout = f"a{i}"
    filt.append(f"[{prev_v}][nv{i}]xfade=transition=fade:duration={XF}:offset={offset:.3f}[{vout}]")
    filt.append(f"[{prev_a}][na{i}]acrossfade=d={XF}[{aout}]")
    prev_v, prev_a = vout, aout
    cum = cum - XF + durs[i]

filter_complex = ";".join(filt)

cmd = ["ffmpeg","-y"] + inputs + [
    "-filter_complex", filter_complex,
    "-map", f"[{prev_v}]", "-map", f"[{prev_a}]",
    "-c:v","libx264","-preset","medium","-crf","17",
    "-c:a","aac","-b:a","192k",
    "-movflags","+faststart",
    OUT
]
print("Total estimated duration:", cum)
r = subprocess.run(cmd, capture_output=True, text=True)
if r.returncode != 0:
    print(r.stderr[-4000:])
    sys.exit(1)
print("DONE ->", OUT)
