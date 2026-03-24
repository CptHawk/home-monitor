# Home Monitor

A self-hosted home monitoring dashboard that unifies security cameras, smart home devices, weather data, and Z-Wave sensors into a single interface. Includes a web dashboard, a TV-optimized view, and a custom Roku channel for displaying live camera grids on TVs throughout your home.

![Dashboard Layout](https://img.shields.io/badge/cameras-5-green) ![Python](https://img.shields.io/badge/python-3.11+-blue) ![License](https://img.shields.io/badge/license-MIT-brightgreen)

## Features

- **UniFi Protect Cameras** — Live MSE video streams and snapshots via go2rtc
- **Google Nest Doorbell** — WebRTC stream bridged through go2rtc for unified viewing
- **Google Nest Thermostat** — Real-time temperature, humidity, HVAC status via SDM API
- **Z-Wave Door Sensors** — Real-time open/closed status via Z-Wave JS UI
- **Weather Underground PWS** — Local weather data from any nearby personal weather station
- **NWS Radar** — Live weather radar loop for your region
- **Weather Panel** — Pillow-rendered current conditions panel with outside/inside temps, humidity, wind, rain, UV, pressure, and thermostat status
- **7-Day NWS Forecast** — Pillow-rendered forecast panel with high/low temps, precipitation chance, and daily conditions from the National Weather Service API
- **Thermostat Integration** — Real-time Nest thermostat data (mode, HVAC status, setpoint) displayed in weather panel and ffmpeg grid overlay
- **Roku TV Channel** — Custom sideloaded channel that displays a live HLS grid of all cameras with live RTSPS cameras, Pillow-rendered weather panels, 7-day forecast, and thermostat overlay
- **Web Dashboard** — Responsive dark-themed UI accessible from any browser
- **TV Dashboard** — 1920x1080 optimized layout for large displays

## Architecture

```
                                ┌─────────────┐
[UniFi Protect] ──RTSPS──────► │             │
[Nest Doorbell] ──WebRTC─────► │   go2rtc    │ ◄── MJPEG/RTSP/HLS/MSE out
[Nest Thermostat] ──SDM API──► │  :1984      │
                                └──────┬──────┘
                                       │
[Weather Underground] ──HTTP──►  ┌─────┴──────┐     ┌──────────────┐
[NWS Radar] ──HTTP───────────►  │  FastAPI    │────►│ Web Browser  │
[Z-Wave JS UI] ──Socket.IO──►  │  :8092      │     │ (Dashboard)  │
                                └──────┬──────┘     └──────────────┘
                                       │
                                ┌──────┴──────┐     ┌──────────────┐
                                │   ffmpeg    │────►│  Roku TV     │
                                │ grid-stream │     │ (HLS Player) │
                                └─────────────┘     └──────────────┘
```

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/home-monitor.git
cd home-monitor
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install Python dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Start go2rtc (camera stream bridge)

```bash
cd go2rtc
cp config/go2rtc.yaml.example config/go2rtc.yaml
# Edit config/go2rtc.yaml with your camera RTSP URLs and Nest credentials
docker compose up -d
cd ..
```

### 4. Start Z-Wave JS UI (optional, for door sensors)

```bash
cd zwave
docker compose up -d
cd ..
```

Open `http://YOUR_SERVER:8091` to configure your Z-Wave USB stick.

### 5. Start the dashboard

```bash
./start-monitor.sh
```

Open `http://YOUR_SERVER:8092` in your browser.

### 6. Start the Roku grid stream (optional)

```bash
# Start the Pillow-rendered weather + forecast panels (updates every 30s)
screen -dmS weatherpanel python3 scripts/render-weather-panel.py

# Start the info overlay data fetcher (for ffmpeg drawtext fallback)
screen -dmS infooverlay bash scripts/info-overlay.sh

# Start the ffmpeg grid stream with live RTSPS cameras + panels
# Edit scripts/start-grid.sh with your camera RTSP URLs first
screen -dmS gridstream bash scripts/start-grid.sh
```

### 7. Deploy to Roku TVs (optional)

First, enable Developer Mode on each Roku:

1. On the Roku remote, press: **Home (x3), Up (x2), Right, Left, Right, Left, Right**
2. Accept the license agreement and set a developer password
3. The Roku will reboot with Developer Mode enabled

Then build and deploy:

```bash
cd roku
# Edit components/DashboardScene.brs — set YOUR_SERVER_IP
./build.sh ROKU_IP rokudev_password
```

## Prerequisites

| Component | Required For |
|-----------|-------------|
| **Docker** | go2rtc, Z-Wave JS UI |
| **Python 3.11+** | FastAPI backend |
| **ffmpeg** | Roku grid stream |
| **Pillow (Python)** | Weather and forecast panel rendering |
| **chromium** | TV screenshot fallback (optional) |
| **UniFi Protect** | Camera snapshots and RTSP streams |
| **Z-Wave USB Stick** | Door/window sensors (tested with Zooz ZST39 LR) |

## Google Nest Setup

The Nest integration requires a Google Device Access project ($5 one-time fee):

1. Create a project at https://console.nest.google.com/device-access
2. Create a Google Cloud project with the Smart Device Management API enabled
3. Create OAuth 2.0 credentials (Web application type)
4. Set redirect URI to `https://www.google.com` (for manual code exchange)
5. Add your Google account as a test user in the OAuth consent screen
6. Run the OAuth flow:

```bash
# Generate auth URL
curl http://YOUR_SERVER:8092/api/nest/auth

# Visit the URL, authorize, copy the ?code= parameter from the redirect
# Exchange the code for tokens:
curl -X POST https://oauth2.googleapis.com/token \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "code=YOUR_AUTH_CODE" \
  -d "grant_type=authorization_code" \
  -d "redirect_uri=https://www.google.com"
```

7. Copy the `refresh_token` from the response into your `.env` file

**Note:** If your Google account has Advanced Protection enabled, you'll need to temporarily disable it for the OAuth flow. Re-enable it after — the refresh token persists.

## go2rtc Camera Configuration

go2rtc bridges various camera protocols into standard formats (RTSP, MJPEG, HLS, MSE) that browsers and Roku can consume.

### UniFi Protect Cameras

1. Enable RTSP in UniFi Protect: **Settings > Camera > RTSP**
2. Copy the RTSP URL for each camera
3. Add to `go2rtc/config/go2rtc.yaml`

### Nest Doorbell

go2rtc has native Nest/WebRTC support. Add your SDM API credentials to the config. The doorbell stream will be available alongside your other cameras.

**Note:** Nest Doorbell Wired (3rd gen) does not support the `GenerateImage` snapshot API. go2rtc bridges the WebRTC stream and can serve snapshots via `/api/frame.jpeg`.

## Roku Channel

The custom Roku channel plays a live HLS grid stream generated by ffmpeg combining all camera feeds.

### Layout

```
┌───────────────┬───────────────┬──────────┐
│   Camera 1    │   Camera 2    │          │
│   720x370     │   720x370     │ Doorbell │
├───────────────┼───────────────┤ 480x1080 │
│   Camera 3    │   Camera 4    │          │
│   720x370     │   720x370     │          │
├──────────┬────┬──────────┬────┼──────────┤
│   Radar  │ Weather Panel │  7-Day   │          │
│  480x340 │  (Pillow)    │ Forecast │          │
│          │  480x340     │  480x340 │          │
└──────────┴────┴──────────┴────┴──────────┘
```

### Deploying to multiple Roku TVs

```bash
# Deploy to all Roku TVs on your network
for ip in YOUR_ROKU_IP_1 YOUR_ROKU_IP_2 YOUR_ROKU_IP_3; do
  roku/build.sh $ip your_password
done

# Launch on all TVs via ECP
for ip in YOUR_ROKU_IP_1 YOUR_ROKU_IP_2 YOUR_ROKU_IP_3; do
  curl -s -X POST "http://$ip:8060/launch/dev"
done
```

Roku TVs must have **Developer Mode** enabled (Settings > System > Advanced system settings > Developer settings).

## Z-Wave Sensors

Tested with Aeotec ZW080 Door/Window Sensors and Zooz ZST39 LR USB stick.

### CLI Tool

```bash
python3 scripts/zwave-cli.py getInfo                    # Controller info
python3 scripts/zwave-cli.py getNodes                   # List paired devices
python3 scripts/zwave-cli.py startExclusion             # Unpair old device
python3 scripts/zwave-cli.py stopExclusion
python3 scripts/zwave-cli.py startInclusion 0 '{"name":"Front Door"}'  # Pair new
python3 scripts/zwave-cli.py stopInclusion
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/cameras` | GET | List UniFi Protect cameras |
| `/api/cameras/{id}/snapshot` | GET | JPEG snapshot from camera |
| `/api/thermostat` | GET | Nest thermostat readings |
| `/api/doorbell` | GET | Nest doorbell status |
| `/api/sensors` | GET | Z-Wave sensor states |
| `/api/weather` | GET | Weather Underground PWS data |
| `/api/radar` | GET | NWS radar image (proxied) |
| `/api/hls/grid.m3u8` | GET | HLS grid stream for Roku |
| `/api/tv-screenshot` | GET | Screenshot of TV dashboard |
| `/api/status` | GET | System status |
| `/api/nest/auth` | GET | Start Nest OAuth flow |
| `/ws` | WS | Real-time sensor updates |

## Weather

The dashboard supports two weather sources:

- **Weather Underground PWS** — Pull data from any nearby personal weather station. Find stations at https://www.wunderground.com/wundermap. The WU public API key included works for basic access.
- **NWS Radar** — Animated radar loop from the nearest NEXRAD station. Find your station at https://radar.weather.gov.
- **Weather Panel** — Pillow-rendered current conditions panel with outside/inside temps, humidity, wind, rain, UV, pressure, and thermostat status
- **7-Day NWS Forecast** — Pillow-rendered forecast panel with high/low temps, precipitation chance, and daily conditions from the National Weather Service API
- **Thermostat Integration** — Real-time Nest thermostat data (mode, HVAC status, setpoint) displayed in weather panel and ffmpeg grid overlay

## Services

| Service | Default Port | Purpose |
|---------|-------------|---------|
| Home Monitor | 8092 | Web dashboard + REST API |
| go2rtc | 1984 | Camera stream bridge (RTSP/MJPEG/HLS/MSE) |
| go2rtc RTSP | 8554 | RTSP relay for Roku IP Camera Viewer |
| Z-Wave JS UI | 8091 | Z-Wave sensor management |

## License

MIT
