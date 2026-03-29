#!/bin/bash
# Home Monitor Grid Stream v2 - Cameras Only
# 5 cameras through go2rtc relay, no panel images
# Layout: 4 cameras (2x2) left + doorbell right = 1920x740

HLSDIR="/tmp/hls"
mkdir -p "$HLSDIR"

while true; do
    rm -f "$HLSDIR"/grid*.ts "$HLSDIR"/grid.m3u8

    echo "[$(date)] Starting ffmpeg grid stream (v2 cameras-only)..."

    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -probesize 256000 -analyzeduration 0 -i "rtsp://127.0.0.1:8554/camera-1" \
        -rtsp_transport tcp -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -probesize 256000 -analyzeduration 0 -i "rtsp://127.0.0.1:8554/camera-2" \
        -rtsp_transport tcp -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -probesize 256000 -analyzeduration 0 -i "rtsp://127.0.0.1:8554/camera-3" \
        -rtsp_transport tcp -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -probesize 256000 -analyzeduration 0 -i "rtsp://127.0.0.1:8554/camera-4" \
        -rtsp_transport tcp -fflags +nobuffer+discardcorrupt+genpts -flags low_delay -probesize 256000 -analyzeduration 0 -i "rtsp://127.0.0.1:8554/doorbell" \
        -filter_complex "\
            [0:v]scale=720:360,format=yuv420p[v0];\
            [1:v]scale=720:360,format=yuv420p[v1];\
            [2:v]scale=720:360,format=yuv420p[v2];\
            [3:v]scale=720:360,format=yuv420p[v3];\
            [4:v]scale=480:720,format=yuv420p[doorbell];\
            [v0][v1]hstack=inputs=2[row1];\
            [v2][v3]hstack=inputs=2[row2];\
            [row1][row2]vstack=inputs=2[cameras];\
            [cameras][doorbell]hstack=inputs=2[out]" \
        -map "[out]" -an \
        -c:v libx264 -preset ultrafast -tune zerolatency \
        -b:v 5M -maxrate 5M -bufsize 10M -g 30 -sc_threshold 0 \
        -f hls -hls_time 2 -hls_list_size 30 \
        -hls_flags delete_segments+append_list \
        -hls_segment_filename "$HLSDIR/grid%03d.ts" \
        "$HLSDIR/grid.m3u8"

    echo "[$(date)] ffmpeg exited ($?). Restarting in 5s..."
    sleep 5
done
