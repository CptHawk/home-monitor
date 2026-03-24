#!/bin/bash
# Captures headless browser screenshot of TV dashboard every 15 seconds
# Used as fallback for Roku channel when live HLS isn't available

SERVER="${1:-localhost:8092}"

while true; do
  chromium --headless --disable-gpu --no-sandbox --window-size=1920,1080 \
    --virtual-time-budget=10000 \
    --screenshot=/tmp/tv-dashboard.jpg --screenshot-format=jpeg \
    --hide-scrollbars --disable-features=TranslateUI \
    "http://${SERVER}/tv.html?mode=screenshot" 2>/dev/null
  sleep 15
done
