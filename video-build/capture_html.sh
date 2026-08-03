#!/bin/bash
# Capture an animated HTML card to video via real-time headless-desktop screen recording.
# Usage: capture_html.sh <html_file> <duration_seconds> <out_mp4>
set -e
HTML="$1"
DUR="$2"
OUT="$3"
DISP=:95
PROFILE="/tmp/claude-1002/-home-dev/3d9d4a9c-5252-4847-8455-775de9725d9b/scratchpad/chrome-capture-profile-$$"
rm -rf "$PROFILE"

DISPLAY=$DISP google-chrome \
  --user-data-dir="$PROFILE" \
  --app="file://$HTML" \
  --window-size=1920,1080 --window-position=0,0 \
  --disable-infobars --no-first-run --disable-features=Translate \
  >/tmp/claude-1002/-home-dev/3d9d4a9c-5252-4847-8455-775de9725d9b/scratchpad/chrome-capture.log 2>&1 &
CHROME_PID=$!

sleep 2.5

DISPLAY=$DISP ffmpeg -y -f x11grab -video_size 1920x1080 -framerate 30 \
  -i $DISP.0 -t "$DUR" \
  -c:v libx264 -pix_fmt yuv420p -preset fast -crf 16 \
  "$OUT" 2>>/tmp/claude-1002/-home-dev/3d9d4a9c-5252-4847-8455-775de9725d9b/scratchpad/chrome-capture.log

kill $CHROME_PID 2>/dev/null || true
wait $CHROME_PID 2>/dev/null || true
rm -rf "$PROFILE"
echo "Captured -> $OUT"
