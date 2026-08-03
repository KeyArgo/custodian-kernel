#!/usr/bin/env python3
"""Synthesize per-segment narration with Kokoro TTS.

Usage:
  python synth-narration.py <narration.json> <out_dir> [voice] [speed]

<narration.json> is an array of {"id": ..., "text": ...} objects, one per
video segment. Writes <out_dir>/<id>.wav for each.

Reusable as-is across videos — only the narration JSON and out_dir differ
per product. Voice defaults to am_michael / speed 1.0 (established in the
Codex Guard video); override per-video if a different voice fits better.

Reminder (see TEMPLATE-README.md pitfall list): write numbers as words in
the narration text ("GPT five point six", not "GPT-5.6") — Kokoro reads a
decimal as a sentence break.
"""
import json, sys, os, wave
import numpy as np
from kokoro_onnx import Kokoro

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

narration_path = sys.argv[1]
out_dir = sys.argv[2]
voice = sys.argv[3] if len(sys.argv) > 3 else "am_michael"
speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

k = Kokoro('/home/dev/.local/share/kokoro/kokoro-v1.0.int8.onnx', '/home/dev/.local/share/kokoro/voices-v1.0.bin')

def write_wav(path, samples, sr):
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())

segs = json.load(open(narration_path))
os.makedirs(out_dir, exist_ok=True)

total = 0
for seg in segs:
    samples, sr = k.create(seg['text'], voice=voice, speed=speed, lang='en-us')
    path = f"{out_dir}/{seg['id']}.wav"
    write_wav(path, samples, sr)
    dur = len(samples) / sr
    total += dur
    print(f"{seg['id']}: {dur:.2f}s -> {path}")
print(f"TOTAL narration: {total:.2f}s (voice={voice}, speed={speed})")
