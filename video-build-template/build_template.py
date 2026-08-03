#!/usr/bin/env python3
"""Per-segment video build pipeline — copy this file into your new video's
own video-build-<product>/ folder and edit the CONFIG block below. Do not
edit this template in place; it stays as the clean starting point for the
next video after this one.

Pipeline per segment: extract-or-use-new-clip -> optional icon overlay ->
stretch/trim to target duration -> optional Ken Burns camera -> mux with
padded narration audio -> <id>_final.mp4. Reused verbatim from the Codex
Guard product video (v4) build; only the CONFIG block is product-specific.
"""
import subprocess, os, json, sys

# ============================== CONFIG ====================================
# Edit everything in this block for your video. Leave the pipeline logic
# below untouched unless you're fixing a real bug (check
# TEMPLATE-README.md's pitfall list first — most "bugs" here already have a
# documented cause).

VB = os.path.dirname(os.path.abspath(__file__))          # this video's folder
WORK = f"{VB}/work"                                        # scratch dir for intermediates
NARR = f"{VB}/narration-audio"                              # from synth-narration.py
os.makedirs(WORK, exist_ok=True)

LEAD_PAD = 0.3   # seconds of silence before narration starts in each segment
TAIL_PAD = 0.3   # seconds of silence after narration ends

# Optional: a previously-baked video to pull Ken-Burns still frames from
# (the "compromise" pattern from PIPELINE-PLAYBOOK.md — only needed if
# you're re-using frozen frames from an old render; leave as None if every
# segment in this video is a fresh HTML capture, which is the preferred
# approach for a brand-new video with no prior baked asset to salvage).
FIXED = None  # e.g. f"{VB}/some-prior-render.mp4"

# segment defs: (name, kind, src_start, src_len, narration_id, overlay_png_or_None, camera)
#   kind="new"     -> pulled from NEW_CLIPS[name] (a fresh capture_html.sh output)
#   kind="extract" -> pulled from FIXED at [src_start, src_start+src_len]
#                     (requires FIXED to be set above)
#   camera=None    -> no Ken Burns move, clip plays as-is
#   camera="zoomin-calm" | "zoomin-strong" | "zoomout" -> see CAMERAS below
#
# EXAMPLE (delete and replace with your video's real segment list):
segments = [
    ("s1", "new", None, None, "s1_intro", None, None),
]

# Only needed for kind="new" segments — map segment name to its rendered
# capture_html.sh output.
NEW_CLIPS = {
    "s1": f"{VB}/s1-intro-rendered.mp4",
}

# ============================ END CONFIG ===================================

# Centered zoompan crop. Do not remove the centering x/y expressions --
# without them zoompan defaults to a top-left anchor and crops content off
# the right/bottom edge as it zooms (confirmed for real on the Codex Guard
# video's s7 segment, whose bottom tagline got clipped). See
# TEMPLATE-README.md pitfall #1.
ZX = "iw/2-(iw/zoom/2)"
ZY = "ih/2-(ih/zoom/2)"

CAMERAS = {
    # calm centered zoom-in: readable, "useful" -- for information-dense slides
    "zoomin-calm":   "z='min(1.0+0.0006*on,1.03)':x='%s':y='%s'" % (ZX, ZY),
    # stronger centered zoom-in: more dramatic, for a single emotional/closing beat.
    # Don't use more than once or twice per video or it stops reading as emphasis.
    "zoomin-strong": "z='min(1.0+0.0011*on,1.05)':x='%s':y='%s'" % (ZX, ZY),
    # centered pull-back: starts zoomed in, settles at the full, uncropped frame
    # by the end -- use for the widest/most content-dense slides; it can't clip
    # anything by the time the viewer has finished reading.
    "zoomout":       "z='max(1.05-0.0011*on,1.0)':x='%s':y='%s'" % (ZX, ZY),
}

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

built = []
for name, kind, start, srclen, nid, overlay, camera in segments:
    ndur = narr_dur(nid)
    target = round(ndur + LEAD_PAD + TAIL_PAD, 2)
    print(f"{name}: narration={ndur:.2f}s target={target:.2f}s kind={kind} camera={camera}")

    raw = f"{WORK}/{name}_raw.mp4"
    if kind == "extract":
        if not FIXED:
            print(f"{name}: kind=extract but FIXED is not set in CONFIG"); sys.exit(1)
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

    kb_out = f"{WORK}/{name}_kb.mp4"
    if camera:
        still = f"{WORK}/{name}_still.png"
        # -ss placed AFTER -i preserves the original absolute timeline, which
        # matters if any downstream filter depends on it. Not load-bearing
        # here (this is a fresh still grab), but keep the ordering habit --
        # see TEMPLATE-README.md pitfall #2 for the case where it does matter.
        run(["ffmpeg","-y","-sseof","-0.1","-i",adj,"-frames:v","1", "-update","1", still])
        nframes = int(round(target * 25))
        zexpr = CAMERAS[camera]
        run(["ffmpeg","-y","-loop","1","-i",still,"-t",str(target),
             "-vf", (f"scale=2400:1350,zoompan={zexpr}:"
                     f"d={nframes}:s=1920x1080:fps=25"),
             "-an","-c:v","libx264","-preset","medium","-crf","16", kb_out])
    else:
        kb_out = adj

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
