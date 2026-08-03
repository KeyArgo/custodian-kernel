import json, sys, wave
import numpy as np
from kokoro_onnx import Kokoro

voice = sys.argv[1] if len(sys.argv) > 1 else "am_michael"
speed = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

k = Kokoro('/home/dev/.local/share/kokoro/kokoro-v1.0.int8.onnx', '/home/dev/.local/share/kokoro/voices-v1.0.bin')

def write_wav(path, samples, sr):
    samples = np.clip(samples, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    with wave.open(path, 'wb') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())

segs = json.load(open('/home/dev/custodian-dev/video-build/narration-v2.json'))
out_dir = '/home/dev/custodian-dev/video-build/narration-audio'
import os
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
