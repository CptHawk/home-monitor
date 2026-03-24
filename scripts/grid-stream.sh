#!/bin/bash
# Generates an HLS grid stream combining camera feeds, radar, weather, and thermostat data
# Requires: ffmpeg, curl
#
# Configuration: Set these variables for your environment
UNIFI_IP="${UNIFI_IP:-YOUR_UNIFI_IP}"
SERVER_IP="${SERVER_IP:-YOUR_SERVER_IP}"
WEATHER_STATION="${WEATHER_STATION:-YOUR_STATION_ID}"

# Camera RTSP keys from UniFi Protect (enable RTSP in camera settings)
CAM_SIDE="${CAM_SIDE:-YOUR_SIDE_WALKWAY_RTSP_KEY}"
CAM_FRONT="${CAM_FRONT:-YOUR_FRONT_YARD_RTSP_KEY}"
CAM_DRIVE="${CAM_DRIVE:-YOUR_DRIVEWAY_RTSP_KEY}"
CAM_DECK="${CAM_DECK:-YOUR_DECK_RTSP_KEY}"

# go2rtc address for doorbell snapshots
GO2RTC="${GO2RTC:-http://127.0.0.1:1984}"

# Radar station (NWS)
RADAR_STATION="${RADAR_STATION:-KRAX}"

mkdir -p /tmp/hls

curl -s -o /tmp/radar.gif "https://radar.weather.gov/ridge/standard/${RADAR_STATION}_loop.gif" 2>/dev/null
ffmpeg -y -hide_banner -loglevel error -i /tmp/radar.gif -vf "select=eq(n\,0)" -frames:v 1 /tmp/radar.png 2>/dev/null

# Refresh radar every 5 min
(while true; do sleep 300; curl -s -o /tmp/radar.gif "https://radar.weather.gov/ridge/standard/${RADAR_STATION}_loop.gif"; ffmpeg -y -hide_banner -loglevel error -i /tmp/radar.gif -vf "select=eq(n\,0)" -frames:v 1 /tmp/radar.png; done) &

# Doorbell snapshots every 2s
(while true; do curl -s -o /tmp/doorbell_snap_tmp.jpg "${GO2RTC}/api/frame.jpeg?src=nest-doorbell" 2>/dev/null && mv /tmp/doorbell_snap_tmp.jpg /tmp/doorbell_snap.jpg; sleep 2; done) &

sleep 5

while true; do
  source /tmp/overlay_info.txt 2>/dev/null
  WT="${WX_TEMP:---}"
  WH="${WX_HUMID:---}"
  WW="${WX_WIND:-0}"
  WR="${WX_RAIN:-0}"
  WU="${WX_UV:---}"
  WP="${WX_PRESS:---}"
  IT="${TH_TEMP:---}"
  IH="${TH_HUMID:---}"
  IM="${TH_MODE:---}"
  IV="${TH_HVAC:---}"
  IS="${TH_SET:---}"

  FILTER="[0:v]scale=720:406,format=yuv420p,drawtext=text='Side Walkway':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v0];"
  FILTER+="[1:v]scale=720:406,format=yuv420p,drawtext=text='Front Yard':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v1];"
  FILTER+="[2:v]scale=720:406,format=yuv420p,drawtext=text='Driveway':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v2];"
  FILTER+="[3:v]scale=720:406,format=yuv420p,drawtext=text='Deck':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v3];"
  FILTER+="[4:v]scale=480:1080,format=yuv420p,drawtext=text='Nest Doorbell':fontsize=18:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[doorbell];"
  FILTER+="[5:v]scale=720:268,format=yuv420p[radar];"
  FILTER+="[v0][v1]hstack=inputs=2[row1];"
  FILTER+="[v2][v3]hstack=inputs=2[row2];"
  FILTER+="color=c=#0d0f14:s=720x268:r=5,format=yuv420p,"
  FILTER+="drawtext=text='%{localtime\:%I\:%M %p}':fontsize=42:fontcolor=white:x=30:y=15,"
  FILTER+="drawtext=text='%{localtime\:%A %b %d}':fontsize=18:fontcolor=#888888:x=30:y=65,"
  FILTER+="drawtext=text='OUTSIDE':fontsize=14:fontcolor=#4a9eff:x=30:y=105,"
  FILTER+="drawtext=text='${WT}F   ${WH}%% Humidity':fontsize=22:fontcolor=#ffffff:x=30:y=125,"
  FILTER+="drawtext=text='Wind ${WW}mph   Rain ${WR}in   UV ${WU}':fontsize=16:fontcolor=#aaaaaa:x=30:y=155,"
  FILTER+="drawtext=text='INSIDE':fontsize=14:fontcolor=#4a9eff:x=400:y=105,"
  FILTER+="drawtext=text='${IT}F   ${IH}%% Humidity':fontsize=22:fontcolor=#ffffff:x=400:y=125,"
  FILTER+="drawtext=text='${IM}   HVAC ${IV}   Set ${IS}F':fontsize=16:fontcolor=#aaaaaa:x=400:y=155,"
  FILTER+="drawtext=text='${WP} inHg':fontsize=14:fontcolor=#888888:x=30:y=185,"
  FILTER+="drawtext=text='Doors\: Awaiting sensors':fontsize=14:fontcolor=#666666:x=400:y=185[info];"
  FILTER+="[radar][info]hstack=inputs=2[row3];"
  FILTER+="[row1][row2]vstack=inputs=2[top];"
  FILTER+="[top][row3]vstack=inputs=2[left];"
  FILTER+="[left][doorbell]hstack=inputs=2[out]"

  ffmpeg -hide_banner -loglevel warning \
    -rtsp_transport tcp -timeout 5000000 -i "rtsps://${UNIFI_IP}:7441/${CAM_SIDE}?enableSrtp" \
    -rtsp_transport tcp -timeout 5000000 -i "rtsps://${UNIFI_IP}:7441/${CAM_FRONT}?enableSrtp" \
    -rtsp_transport tcp -timeout 5000000 -i "rtsps://${UNIFI_IP}:7441/${CAM_DRIVE}?enableSrtp" \
    -rtsp_transport tcp -timeout 5000000 -i "rtsps://${UNIFI_IP}:7441/${CAM_DECK}?enableSrtp" \
    -loop 1 -framerate 2 -s 480x480 -i /tmp/doorbell_snap.jpg \
    -loop 1 -framerate 1 -s 600x550 -i /tmp/radar.png \
    -filter_complex "${FILTER}" \
    -map "[out]" -an \
    -c:v libx264 -preset ultrafast -tune zerolatency \
    -b:v 5M -maxrate 5M -bufsize 10M \
    -g 30 -sc_threshold 0 \
    -t 120 \
    -f hls -hls_time 2 -hls_list_size 5 \
    -hls_flags delete_segments+temp_file \
    -hls_segment_filename "/tmp/hls/grid%03d.ts" \
    /tmp/hls/grid.m3u8

  echo "Restarting to refresh data..."
  sleep 1
done
