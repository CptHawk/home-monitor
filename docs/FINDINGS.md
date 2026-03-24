# Technical Findings

Notes and discoveries from building the home monitoring system. Intended to save others time when integrating UniFi Protect cameras, Google Nest devices, go2rtc, and Roku TVs.

## Camera Streaming Findings

### rtspx:// vs rtsps:// Protocol (Critical Discovery)

- UniFi Protect RTSPS connections (port 7441 with `?enableSrtp`) drop after 2-3 minutes
- **Root cause:** SRTP encryption overhead causes Protect to terminate long-lived connections
- **Fix:** Use `rtspx://` protocol in go2rtc instead of `rtsps://`. Drop the `?enableSrtp` suffix
- `rtspx://` produces clean H.264 that ffmpeg can consume without NAL errors
- This applies to **all** UniFi Protect cameras (tested with 4K PoE and 2K WiFi models)

**Before (drops after 2-3 min):**
```yaml
# go2rtc config - BROKEN
streams:
  camera-1: rtsps://YOUR_UNIFI_IP:7441/YOUR_STREAM_KEY?enableSrtp
```

**After (stable indefinitely):**
```yaml
# go2rtc config - WORKING
streams:
  camera-1: rtspx://YOUR_UNIFI_IP:7441/YOUR_STREAM_KEY
```

### go2rtc RTSP Relay NAL Errors

- go2rtc's RTSP relay with `rtsps://` sources produces corrupted H.264 with NAL type 26 (MTAP16) errors
- ffmpeg's RTSP demuxer only supports NAL types 24 (STAP-A) and 28 (FU-A)
- This affects both Protect cameras AND Nest doorbell WebRTC streams
- Switching to `rtspx://` eliminates this for Protect cameras
- Nest doorbell requires explicit transcoding via go2rtc's ffmpeg bridge (see below)

### Nest Doorbell (Wired 3rd Gen) Integration

- Does **not** support the `GenerateImage` snapshot API (WebRTC-only device)
- go2rtc bridges WebRTC to RTSP, but the raw stream has NAL type 26 errors
- **Fix:** Use go2rtc's ffmpeg transcoder: `ffmpeg:nest-doorbell-raw#video=h264#audio=aac`
- Transcoded stream produces clean baseline H.264 + AAC
- CPU cost is negligible at 480x640@15fps with `superfast` preset

```yaml
# go2rtc config for Nest Doorbell
streams:
  nest-doorbell-raw: "nest:?client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET&refresh_token=YOUR_REFRESH_TOKEN&project_id=YOUR_PROJECT_ID&device_id=YOUR_DEVICE_ID"
  nest-doorbell: "ffmpeg:nest-doorbell-raw#video=h264#audio=aac"
```

### UniFi Connect vs Protect Viewport

- **UniFi Connect** is for digital signage, lighting, and EV charging — it is NOT for cameras
- **UniFi Protect Viewport** ($99 HDMI dongle) is the official camera display product
- Neither supports Roku, Chromecast, or smart TV apps
- [j4zzcat/viewport](https://github.com/j4zzcat/viewport) is an open-source alternative using WebSocket H.264 streams

### Roku TV as Camera Display

- Roku has no real web browser (removed from firmware)
- Developer mode allows sideloading BrightScript channels
- Roku's `Video` node plays HLS streams natively
- Only one `Video` node can play at a time — use ffmpeg to composite a multi-camera grid into a single HLS stream
- IP Camera Viewer Pro (Roku app) supports MJPEG streams from go2rtc

### Snapshot API Reliability

- UniFi Protect snapshot API occasionally returns HTTP 500 errors, especially under load
- 4K cameras take longer to generate snapshots than 2K cameras
- Always validate JPEG magic bytes (`FF D8`) before using snapshot files
- go2rtc `frame.jpeg` endpoint returns an empty body until the WebRTC connection is established (~30s warmup)

### Google Nest SDM API with Advanced Protection

- Google Advanced Protection Program blocks unverified OAuth apps
- **Workaround:** Temporarily disable Advanced Protection, complete the OAuth flow, then re-enable
- Refresh tokens survive Advanced Protection re-enablement
- You must add yourself as a test user in the Google Cloud OAuth consent screen
- Use `https://www.google.com` as the redirect URI for server-side apps without a public domain
