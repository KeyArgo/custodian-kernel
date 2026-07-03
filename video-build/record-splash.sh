#!/bin/bash
VBUILD="/mnt/homes/galileo/argo/Development/hermes-hackathon-2026/video-build"
SCRATCHPAD="/home/argo/tmp/claude-1000/-home-argo/95f71b58-bb72-4d1f-b422-3001d9b0d117/scratchpad/v6"

echo "Opening splash..."
rm -rf /tmp/csp-record
google-chrome --no-sandbox \
  --user-data-dir=/tmp/csp-record \
  --app="file://$VBUILD/custodian-splash.html" \
  --window-size=1920,1080 --window-position=0,0 \
  2>/dev/null &
CHROME_PID=$!

sleep 3

# Raise Chrome to front
WIN=$(xdotool search --pid $CHROME_PID 2>/dev/null | head -1)
if [ -n "$WIN" ]; then
  xdotool windowraise $WIN
  xdotool windowfocus $WIN
  wmctrl -i -r $WIN -b add,fullscreen
  echo "Chrome raised: $WIN"
else
  wmctrl -a "Cinematic Splash" 2>/dev/null
  echo "Used wmctrl fallback"
fi

sleep 2
echo "Recording 10s — watch the animation..."

ffmpeg -f x11grab -video_size 1920x1080 -framerate 60 \
  -i :0.0 -t 10 \
  -c:v libx264 -pix_fmt yuv420p -preset fast -crf 18 \
  "$SCRATCHPAD/splash_raw.mp4" -y 2>/dev/null

echo "Done recording."
kill $CHROME_PID 2>/dev/null

# Trim first 1s stutter, keep 7s
ffmpeg -i "$SCRATCHPAD/splash_raw.mp4" -ss 1 -t 7 \
  -c:v libx264 -pix_fmt yuv420p -preset fast \
  "$SCRATCHPAD/splash.mp4" -y 2>/dev/null

echo "Splash saved: $SCRATCHPAD/splash.mp4"
echo "Now tell Claude to rebuild the final video."
