#!/usr/bin/env python3
"""Build custodian-guard-product-v2.mp4 from scratch: fixed segments + new splash/CTA,
narration audio muxed per segment, Ken Burns on static cards, crossfade transitions."""
import subprocess, os, json, sys

VB = "/home/dev/custodian-dev/video-build"
SCRATCH = "/tmp/claude-1002/-home-dev/1442337b-0834-411f-8d50-e94f80bceffa/scratchpad"
FIXED = f"{VB}/custodian-guard-product-v1-FIXED.mp4"
NARR = f"{VB}/narration-audio"
WORK = f"{SCRATCH}/build-v2"
os.makedirs(WORK, exist_ok=True)

LEAD_PAD = 0.3
TAIL_PAD = 0.3

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("CMD FAILED:", " ".join(cmd))
        print(r.stderr[-3000:])
        sys.exit(1)

def probe_dur(path):
    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                         "-of","default=nw=1:nk=1", path], capture_output=True, text=True)
    return float(r.stdout.strip())

def narr_dur(seg_id):
    return probe_dur(f"{NARR}/{seg_id}.wav")

# segment defs: (name, kind, src_start, src_len, narration_id, overlay_png_or_None, kenburns)
segments = [
    ("s1", "extract", 0.0,   15.0,  "s1_problem",  None, True),
    ("s2", "new",     None,  None,  "s2_splash",   None, False),
    ("s3", "extract", 25.0,  20.0,  "s3_architecture", None, True),
    ("s4", "extract", 45.0,  10.0,  "s4_receipts", None, True),
    ("s5", "extract", 55.0,  16.2,  "s5_terminal", None, True),
    ("s6", "extract", 71.2,  20.0,  "s6_attack",   f"{SCRATCH}/attack-icon-overlay.png", True),
    ("s7", "extract", 91.2,  20.0,  "s7_grid",     None, True),
    ("s8", "extract", 111.2, 12.0,  "s8_painpoint",None, True),
    ("s9", "new",     None,  None,  "s9_cta",      None, False),
]

NEW_CLIPS = {
    "s2": f"{VB}/splash-v2-rendered.mp4",
    "s9": f"{VB}/cta-v2-rendered.mp4",
}

built = []
for name, kind, start, srclen, nid, overlay, kb in segments:
    ndur = narr_dur(nid)
    target = round(ndur + LEAD_PAD + TAIL_PAD, 2)
    print(f"{name}: narration={ndur:.2f}s target={target:.2f}s kind={kind}")

    raw = f"{WORK}/{name}_raw.mp4"
    if kind == "extract":
        run(["ffmpeg","-y","-ss",str(start),"-i",FIXED,"-t",str(srclen),
             "-an","-c:v","libx264","-preset","medium","-crf","16", raw])
    else:
        raw = NEW_CLIPS[name]

    src_dur = probe_dur(raw)

    patched = f"{WORK}/{name}_patched.mp4"
    if overlay:
        run(["ffmpeg","-y","-i",raw,"-i",overlay,
             "-filter_complex","[0:v][1:v]overlay=0:0[v]",
             "-map","[v]","-an","-c:v","libx264","-preset","medium","-crf","16", patched])
    else:
        patched = raw

    # adjust duration: extend via tpad (clone last frame) or trim
    adj = f"{WORK}/{name}_adj.mp4"
    if target > src_dur + 0.02:
        extend = target - src_dur
        run(["ffmpeg","-y","-i",patched,
             "-vf", f"tpad=stop_mode=clone:stop_duration={extend:.3f}",
             "-an","-c:v","libx264","-preset","medium","-crf","16", adj])
    elif target < src_dur - 0.02:
        run(["ffmpeg","-y","-i",patched,"-t",str(target),
             "-an","-c:v","libx264","-preset","medium","-crf","16", adj])
    else:
        adj = patched

    # Ken Burns (subtle slow zoom) for static extracted cards only.
    # zoompan explodes frame count if fed a multi-frame video (d is applied
    # PER INPUT FRAME), so drive it from a single still image instead.
    kb_out = f"{WORK}/{name}_kb.mp4"
    if kb:
        still = f"{WORK}/{name}_still.png"
        run(["ffmpeg","-y","-sseof","-0.1","-i",adj,"-frames:v","1", still])
        nframes = int(round(target * 25))
        run(["ffmpeg","-y","-loop","1","-i",still,"-t",str(target),
             "-vf", (f"scale=2400:1350,zoompan=z='min(zoom+0.0007,1.045)':"
                     f"d={nframes}:s=1920x1080:fps=25"),
             "-an","-c:v","libx264","-preset","medium","-crf","16", kb_out])
    else:
        kb_out = adj

    # build audio: lead silence + narration + tail silence, padded to exact target
    aout = f"{WORK}/{name}_audio.wav"
    run(["ffmpeg","-y","-i",f"{NARR}/{nid}.wav",
         "-af", f"adelay={int(LEAD_PAD*1000)}|{int(LEAD_PAD*1000)},apad=whole_dur={target}",
         "-ar","48000","-ac","1", aout])

    final_seg = f"{WORK}/{name}_final.mp4"
    run(["ffmpeg","-y","-i",kb_out,"-i",aout,
         "-map","0:v","-map","1:a","-c:v","libx264","-preset","medium","-crf","16",
         "-c:a","aac","-b:a","192k","-shortest", final_seg])

    built.append((name, final_seg, probe_dur(final_seg)))

print("\nBuilt segments:")
for name, path, dur in built:
    print(f"  {name}: {dur:.2f}s -> {path}")

json.dump(built, open(f"{WORK}/segments.json","w"))
