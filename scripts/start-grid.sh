#!/bin/bash
# Home Monitor Grid Stream - 1920x1080 HLS for Roku TVs
# Direct RTSPS to UniFi Protect + doorbell via go2rtc relay
# Restarts every 5 min to pick up fresh info panels + recover from stream drops

HLSDIR="/tmp/hls"
mkdir -p "$HLSDIR"

while true; do
    echo "[$(date)] Starting ffmpeg grid stream (5 min cycle)..."

    ffmpeg -hide_banner -loglevel error \
        -err_detect ignore_err \
        -rtsp_transport tcp -timeout 5000000 -i "rtsps://YOUR_UNIFI_IP:7441/YOUR_STREAM_KEY_1?enableSrtp" \
        -err_detect ignore_err \
        -rtsp_transport tcp -timeout 5000000 -i "rtsps://YOUR_UNIFI_IP:7441/YOUR_STREAM_KEY_2?enableSrtp" \
        -err_detect ignore_err \
        -rtsp_transport tcp -timeout 5000000 -i "rtsps://YOUR_UNIFI_IP:7441/YOUR_STREAM_KEY_3?enableSrtp" \
        -err_detect ignore_err \
        -rtsp_transport tcp -timeout 5000000 -i "rtsps://YOUR_UNIFI_IP:7441/YOUR_STREAM_KEY_4?enableSrtp" \
        -loop 1 -framerate 0.5 -i /tmp/doorbell_snap.jpg \
        -loop 1 -framerate 0.1 -i /tmp/radar.png \
        -loop 1 -framerate 0.1 -i /tmp/weather_panel.png \
        -loop 1 -framerate 0.1 -i /tmp/forecast_panel.png \
        -filter_complex "\
            [0:v]scale=720:370,format=yuv420p,drawtext=text='Camera 1':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v0];\
            [1:v]scale=720:370,format=yuv420p,drawtext=text='Camera 2':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v1];\
            [2:v]scale=720:370,format=yuv420p,drawtext=text='Camera 3':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v2];\
            [3:v]scale=720:370,format=yuv420p,drawtext=text='Camera 4':fontsize=20:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[v3];\
            [4:v]scale=480:1080,format=yuv420p,drawtext=text='Nest Doorbell':fontsize=18:fontcolor=white:x=8:y=8:box=1:boxcolor=black@0.5:boxborderw=3[doorbell];\
            [5:v]scale=480:340,format=yuv420p[radar];\
            [6:v]scale=480:340,format=yuv420p[weather];\
            [7:v]scale=480:340,format=yuv420p[forecast];\
            [v0][v1]hstack=inputs=2[row1];\
            [v2][v3]hstack=inputs=2[row2];\
            [row1][row2]vstack=inputs=2[cameras];\
            [radar][weather][forecast]hstack=inputs=3[bottom];\
            [cameras][bottom]vstack=inputs=2[left];\
            [left][doorbell]hstack=inputs=2[out]" \
        -map "[out]" -an \
        -c:v libx264 -preset ultrafast -tune zerolatency \
        -b:v 5M -maxrate 5M -bufsize 10M -g 30 -sc_threshold 0 \
        -t 300 \
        -f hls -hls_time 2 -hls_list_size 10 \
        -hls_flags delete_segments+append_list \
        -hls_segment_filename "$HLSDIR/grid%03d.ts" \
        "$HLSDIR/grid.m3u8"

    echo "[$(date)] Cycle ended ($?). Restarting in 2s..."
    sleep 2
done
