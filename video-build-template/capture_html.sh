#!/bin/bash
# Capture an animated HTML card to video via real-time headless-desktop screen recording.
# Usage: capture_html.sh <html_file> <duration_seconds> <out_mp4>
#
# Reusable as-is across videos. Nothing here is product-specific. Uses a
# fresh mktemp scratch dir per invocation instead of a hardcoded session
# path, so this script works from any checkout.
set -e
HTML="$1"
DUR="$2"
OUT="$3"
DISP=:95
SCRATCH="$(mktemp -d)"
PROFILE="$SCRATCH/chrome-capture-profile-$$"
LOG="$SCRATCH/chrome-capture.log"
rm -rf "$PROFILE"

cleanup() { rm -rf "$SCRATCH"; }
trap cleanup EXIT

DISPLAY=$DISP google-chrome \
  --user-data-dir="$PROFILE" \
  --app="file://$HTML" \
  --window-size=1920,1080 --window-position=0,0 \
  --disable-infobars --no-first-run --disable-features=Translate \
  >"$LOG" 2>&1 &
CHROME_PID=$!

sleep 2.5

DISPLAY=$DISP ffmpeg -y -f x11grab -video_size 1920x1080 -framerate 30 \
  -i $DISP.0 -t "$DUR" \
  -c:v libx264 -pix_fmt yuv420p -preset fast -crf 16 \
  "$OUT" 2>>"$LOG"

kill $CHROME_PID 2>/dev/null || true
wait $CHROME_PID 2>/dev/null || true
echo "Captured -> $OUT"
