#!/bin/bash
# Home Monitor Grid Stream - Live RTSP via go2rtc (rtspx protocol)
# All cameras through go2rtc relay - one connection each to Protect
#
# KEY INSIGHT: Use rtspx:// in go2rtc config instead of rtsps://.
# rtsps:// (SRTP) connections to UniFi Protect drop after 2-3 minutes.
# rtspx:// produces clean H.264 that ffmpeg can consume without NAL errors.
# See docs/FINDINGS.md for details.

HLSDIR="/tmp/hls"
mkdir -p "$HLSDIR"

while true; do
    rm -f "$HLSDIR"/grid*.ts "$HLSDIR"/grid.m3u8

    echo "[$(date)] Starting ffmpeg grid stream (live RTSP via go2rtc)..."

    ffmpeg -hide_banner -loglevel warning \
        -rtsp_transport tcp -fflags +discardcorrupt+genpts -i "rtsp://127.0.0.1:8554/camera-1" \
        -rtsp_transport tcp -fflags +discardcorrupt+genpts -i "rtsp://127.0.0.1:8554/camera-2" \
        -rtsp_transport tcp -fflags +discardcorrupt+genpts -i "rtsp://127.0.0.1:8554/camera-3" \
        -rtsp_transport tcp -fflags +discardcorrupt+genpts -i "rtsp://127.0.0.1:8554/camera-4" \
        -rtsp_transport tcp -fflags +discardcorrupt+genpts -i "rtsp://127.0.0.1:8554/nest-doorbell" \
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
        -f hls -hls_time 2 -hls_list_size 10 \
        -hls_flags delete_segments+append_list \
        -hls_segment_filename "$HLSDIR/grid%03d.ts" \
        "$HLSDIR/grid.m3u8"

    echo "[$(date)] ffmpeg exited ($?). Restarting in 5s..."
    sleep 5
done
