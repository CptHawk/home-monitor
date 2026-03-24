#!/bin/bash
# Snapshot fallback - grabs JPEG snapshots from UniFi Protect API and go2rtc
# Used as reference/fallback when live RTSP grid is not running.
# The live grid stream (start-grid.sh) is preferred over snapshot compositing.

API="http://127.0.0.1:8092/api"
CAM1="YOUR_CAMERA_ID_1"
CAM2="YOUR_CAMERA_ID_2"
CAM3="YOUR_CAMERA_ID_3"
CAM4="YOUR_CAMERA_ID_4"

grab() {
    local url="$1" dest="$2"
    curl -s --max-time 10 -o "${dest}.tmp" "$url"
    if [ -s "${dest}.tmp" ] && python3 -c "
import sys
with open('${dest}.tmp','rb') as f:
    sys.exit(0 if f.read(2)==b'\xff\xd8' else 1)
" 2>/dev/null; then
        mv -f "${dest}.tmp" "$dest"
    else
        rm -f "${dest}.tmp"
    fi
}

while true; do
    grab "$API/cameras/$CAM1/snapshot" /tmp/cam_1.jpg
    grab "$API/cameras/$CAM2/snapshot" /tmp/cam_2.jpg
    grab "$API/cameras/$CAM3/snapshot" /tmp/cam_3.jpg
    grab "$API/cameras/$CAM4/snapshot" /tmp/cam_4.jpg
    grab "http://127.0.0.1:1984/api/frame.jpeg?src=nest-doorbell" /tmp/doorbell_snap.jpg
    sleep 2
done
