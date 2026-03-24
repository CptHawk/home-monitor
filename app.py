#!/usr/bin/env python3
"""Home Monitoring Web UI — FastAPI backend

Integrates UniFi Protect cameras, Google Nest (thermostat + doorbell),
Z-Wave door sensors, Weather Underground PWS data, and NWS radar.
Serves a web dashboard and provides HLS grid stream for Roku TVs.
"""
import os, json, time, asyncio, ssl
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ---------------------------------------------------------------------------
# Config (all from .env)
# ---------------------------------------------------------------------------
UNIFI_HOST = os.getenv("UNIFI_HOST", "YOUR_UNIFI_IP")
UNIFI_USERNAME = os.getenv("UNIFI_USERNAME", "")
UNIFI_PASSWORD = os.getenv("UNIFI_PASSWORD", "")

NEST_PROJECT_ID = os.getenv("NEST_PROJECT_ID", "")
NEST_CLIENT_ID = os.getenv("NEST_CLIENT_ID", "")
NEST_CLIENT_SECRET = os.getenv("NEST_CLIENT_SECRET", "")
NEST_REFRESH_TOKEN = os.getenv("NEST_REFRESH_TOKEN", "")

ZWAVE_HOST = os.getenv("ZWAVE_HOST", "localhost")
ZWAVE_PORT = int(os.getenv("ZWAVE_PORT", "8091"))

GO2RTC_HOST = os.getenv("GO2RTC_HOST", "localhost")
GO2RTC_PORT = int(os.getenv("GO2RTC_PORT", "1984"))

WU_STATION_ID = os.getenv("WU_STATION_ID", "")
WU_API_KEY = os.getenv("WU_API_KEY", "YOUR_WU_API_KEY")
RADAR_STATION = os.getenv("RADAR_STATION", "YOUR_RADAR_STATION")

SERVER_HOST = os.getenv("SERVER_HOST", "localhost")
SERVER_PORT = os.getenv("SERVER_PORT", "8092")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
unifi_cookies = None
unifi_cameras_cache = []
unifi_cache_time = 0

nest_access_token = os.getenv("NEST_ACCESS_TOKEN", "")
nest_token_expiry = 0
thermostat_cache = {}
thermostat_cache_time = 0

zwave_sensors = {}
ws_clients: list[WebSocket] = []

# ---------------------------------------------------------------------------
# UniFi Protect helpers
# ---------------------------------------------------------------------------
async def unifi_login():
    global unifi_cookies
    if not UNIFI_USERNAME:
        return False
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        r = await client.post(
            f"https://{UNIFI_HOST}/api/auth/login",
            json={"username": UNIFI_USERNAME, "password": UNIFI_PASSWORD, "remember": True},
        )
        if r.status_code == 200:
            unifi_cookies = dict(r.cookies)
            return True
    return False


async def unifi_get_cameras():
    global unifi_cameras_cache, unifi_cache_time
    now = time.time()
    if unifi_cameras_cache and now - unifi_cache_time < 300:
        return unifi_cameras_cache

    if not unifi_cookies:
        if not await unifi_login():
            return []

    async with httpx.AsyncClient(verify=False, timeout=10, cookies=unifi_cookies) as client:
        r = await client.get(f"https://{UNIFI_HOST}/proxy/protect/api/cameras")
        if r.status_code == 401:
            if await unifi_login():
                r = await client.get(
                    f"https://{UNIFI_HOST}/proxy/protect/api/cameras",
                    cookies=unifi_cookies,
                )
        if r.status_code == 200:
            cams = r.json()
            unifi_cameras_cache = [
                {
                    "id": c["id"],
                    "name": c.get("name", "Unknown"),
                    "type": c.get("type", ""),
                    "state": c.get("state", ""),
                    "host": c.get("host", ""),
                    "channels": [
                        {
                            "id": ch.get("id"),
                            "name": ch.get("name", ""),
                            "rtspAlias": ch.get("rtspAlias", ""),
                            "width": ch.get("width", 0),
                            "height": ch.get("height", 0),
                            "isRtspEnabled": ch.get("isRtspEnabled", False),
                        }
                        for ch in c.get("channels", [])
                    ],
                }
                for c in cams
            ]
            unifi_cache_time = now
    return unifi_cameras_cache


async def unifi_snapshot(camera_id: str) -> Optional[bytes]:
    if not unifi_cookies:
        if not await unifi_login():
            return None

    async with httpx.AsyncClient(verify=False, timeout=15, cookies=unifi_cookies) as client:
        r = await client.get(
            f"https://{UNIFI_HOST}/proxy/protect/api/cameras/{camera_id}/snapshot",
            params={"force": "true", "ts": str(int(time.time() * 1000))},
        )
        if r.status_code == 401:
            if await unifi_login():
                r = await client.get(
                    f"https://{UNIFI_HOST}/proxy/protect/api/cameras/{camera_id}/snapshot",
                    params={"force": "true", "ts": str(int(time.time() * 1000))},
                    cookies=unifi_cookies,
                )
        if r.status_code == 200:
            return r.content
    return None

# ---------------------------------------------------------------------------
# Google Nest helpers
# ---------------------------------------------------------------------------
async def nest_refresh_token_fn():
    global nest_access_token, nest_token_expiry
    if not NEST_REFRESH_TOKEN or not NEST_CLIENT_ID:
        return False
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": NEST_CLIENT_ID,
                "client_secret": NEST_CLIENT_SECRET,
                "refresh_token": NEST_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
        )
        if r.status_code == 200:
            data = r.json()
            nest_access_token = data["access_token"]
            nest_token_expiry = time.time() + data.get("expires_in", 3600) - 60
            return True
    return False


async def nest_get_token():
    global nest_access_token, nest_token_expiry
    if not nest_access_token or time.time() > nest_token_expiry:
        await nest_refresh_token_fn()
    return nest_access_token


async def nest_get_devices():
    token = await nest_get_token()
    if not token:
        return []
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"https://smartdevicemanagement.googleapis.com/v1/enterprises/{NEST_PROJECT_ID}/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code == 200:
            return r.json().get("devices", [])
    return []


async def nest_get_thermostat():
    global thermostat_cache, thermostat_cache_time
    now = time.time()
    if thermostat_cache and now - thermostat_cache_time < 30:
        return thermostat_cache

    devices = await nest_get_devices()
    for d in devices:
        if "THERMOSTAT" in d.get("type", ""):
            traits = d.get("traits", {})
            temp_trait = traits.get("sdm.devices.traits.Temperature", {})
            humidity_trait = traits.get("sdm.devices.traits.Humidity", {})
            mode_trait = traits.get("sdm.devices.traits.ThermostatMode", {})
            setpoint_heat = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
            hvac_trait = traits.get("sdm.devices.traits.ThermostatHvac", {})

            temp_c = temp_trait.get("ambientTemperatureCelsius")
            temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else None

            thermostat_cache = {
                "temperature_c": temp_c,
                "temperature_f": temp_f,
                "humidity": humidity_trait.get("ambientHumidityPercent"),
                "mode": mode_trait.get("mode", "UNKNOWN"),
                "hvac_status": hvac_trait.get("status", "UNKNOWN"),
                "heat_setpoint_c": setpoint_heat.get("heatCelsius"),
                "cool_setpoint_c": setpoint_heat.get("coolCelsius"),
                "updated": datetime.now(timezone.utc).isoformat(),
            }
            thermostat_cache_time = now
            return thermostat_cache
    return {"error": "No thermostat found or Nest not configured"}


async def nest_get_doorbell_events():
    devices = await nest_get_devices()
    for d in devices:
        if "DOORBELL" in d.get("type", ""):
            traits = d.get("traits", {})
            motion = traits.get("sdm.devices.traits.CameraMotion", {})
            person = traits.get("sdm.devices.traits.CameraPerson", {})
            chime = traits.get("sdm.devices.traits.DoorbellChime", {})
            stream = traits.get("sdm.devices.traits.CameraLiveStream", {})

            return {
                "name": d.get("parentRelations", [{}])[0].get("displayName", "Doorbell"),
                "device_id": d.get("name", ""),
                "hasMotion": bool(motion),
                "hasPerson": bool(person),
                "hasChime": bool(chime),
                "supportsStream": "WEB_RTC" in stream.get("supportedProtocols", []),
                "maxResolution": traits.get("sdm.devices.traits.CameraImage", {}).get("maxImageResolution", {}),
                "updated": datetime.now(timezone.utc).isoformat(),
            }
    return {"error": "No doorbell found or Nest not configured"}


_doorbell_device_id = None

async def nest_get_doorbell_device_id():
    global _doorbell_device_id
    if _doorbell_device_id:
        return _doorbell_device_id
    devices = await nest_get_devices()
    for d in devices:
        if "DOORBELL" in d.get("type", ""):
            _doorbell_device_id = d.get("name", "")
            return _doorbell_device_id
    return None


async def nest_doorbell_snapshot() -> Optional[bytes]:
    """Get a snapshot from the Nest doorbell via GenerateImage command.
    Note: 3rd gen wired doorbells do NOT support this — WebRTC only.
    Works with legacy and 2nd gen battery doorbells.
    """
    device_id = await nest_get_doorbell_device_id()
    if not device_id:
        return None
    token = await nest_get_token()
    if not token:
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://smartdevicemanagement.googleapis.com/v1/{device_id}:executeCommand",
            headers={"Authorization": f"Bearer {token}"},
            json={"command": "sdm.devices.commands.CameraImage.GenerateImage", "params": {}},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        results = data.get("results", {})
        img_url = results.get("url")
        img_token = results.get("token")
        if not img_url:
            return None

        img_r = await client.get(
            img_url,
            headers={"Authorization": f"Basic {img_token}"},
        )
        if img_r.status_code == 200:
            return img_r.content
    return None

# ---------------------------------------------------------------------------
# Z-Wave helpers (Socket.IO to Z-Wave JS UI)
# ---------------------------------------------------------------------------
def zwave_call_api_sync(api_name, args=None):
    """Synchronous Z-Wave API call via Socket.IO."""
    if args is None:
        args = []
    import threading
    import websocket as ws_sync
    URL = f"ws://{ZWAVE_HOST}:{ZWAVE_PORT}/socket.io/?EIO=4&transport=websocket"
    result = {}
    done = threading.Event()

    def on_message(ws_conn, msg):
        if msg == "2":
            ws_conn.send("3")
            return
        if msg.startswith("0"):
            ws_conn.send("40")
        elif msg.startswith("40"):
            payload = json.dumps(["ZWAVE_API", {"api": api_name, "args": args}])
            ws_conn.send(f"421{payload}")
        elif msg.startswith("43"):
            ack_data = msg[2:]
            i = 0
            while i < len(ack_data) and ack_data[i].isdigit():
                i += 1
            try:
                data = json.loads(ack_data[i:])
                result["data"] = data[0] if isinstance(data, list) and len(data) > 0 else data
            except Exception:
                pass
            done.set()

    ws_conn = ws_sync.WebSocketApp(URL, on_message=on_message)
    t = threading.Thread(target=ws_conn.run_forever)
    t.daemon = True
    t.start()
    done.wait(timeout=10)
    if "data" in result and result["data"].get("success"):
        return result["data"].get("result")
    return None


async def zwave_get_nodes():
    return await asyncio.to_thread(zwave_call_api_sync, "getNodes")

# ---------------------------------------------------------------------------
# WebSocket broadcast to browser clients
# ---------------------------------------------------------------------------
async def broadcast(message: dict):
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)

# ---------------------------------------------------------------------------
# Background Z-Wave listener
# ---------------------------------------------------------------------------
async def zwave_listener():
    """Listen for Z-Wave value updates via Socket.IO websocket."""
    import websockets
    URL = f"ws://{ZWAVE_HOST}:{ZWAVE_PORT}/socket.io/?EIO=4&transport=websocket"
    while True:
        try:
            async with websockets.connect(URL) as ws:
                msg = await ws.recv()
                await ws.send("40")
                msg = await ws.recv()

                await ws.send("42" + json.dumps(["SUBSCRIBE", ["values", "nodes"]]))

                while True:
                    msg = await ws.recv()
                    if msg == "2":
                        await ws.send("3")
                        continue
                    if msg.startswith("42"):
                        try:
                            data = json.loads(msg[2:])
                            event = data[0] if data else ""
                            if event == "VALUE_UPDATED" and len(data) > 1:
                                val = data[1]
                                node_id = val.get("nodeId")
                                cc = val.get("commandClass")
                                prop = val.get("property")
                                value = val.get("newValue")
                                key = f"{node_id}_{cc}_{prop}"
                                zwave_sensors[key] = {
                                    "nodeId": node_id,
                                    "commandClass": cc,
                                    "property": prop,
                                    "value": value,
                                    "updated": datetime.now(timezone.utc).isoformat(),
                                }
                                await broadcast({"type": "sensor", "data": zwave_sensors[key]})
                        except (json.JSONDecodeError, IndexError):
                            pass
        except Exception as e:
            print(f"Z-Wave listener error: {e}, reconnecting in 5s...")
            await asyncio.sleep(5)

# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(zwave_listener())
    yield
    task.cancel()

app = FastAPI(title="Home Monitor", lifespan=lifespan)

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/api/cameras")
async def api_cameras():
    cams = await unifi_get_cameras()
    return JSONResponse([
        {
            "id": c["id"],
            "name": c["name"],
            "state": c["state"],
            "rtsp": next(
                (ch["rtspAlias"] for ch in c["channels"] if ch.get("isRtspEnabled")),
                None,
            ),
        }
        for c in cams
    ])


@app.get("/api/cameras/{camera_id}/snapshot")
async def api_camera_snapshot(camera_id: str):
    data = await unifi_snapshot(camera_id)
    if data:
        return Response(content=data, media_type="image/jpeg")
    return JSONResponse({"error": "Failed to get snapshot"}, status_code=502)


@app.get("/api/doorbell/snapshot")
async def api_doorbell_snapshot():
    """Nest Doorbell 3rd gen only supports WebRTC, no snapshot API.
    For legacy/battery doorbells, this uses GenerateImage.
    """
    data = await nest_doorbell_snapshot()
    if data:
        return Response(content=data, media_type="image/jpeg")
    return JSONResponse(
        {"error": "Doorbell snapshot unavailable. 3rd gen wired doorbells only support WebRTC."},
        status_code=501,
    )


@app.get("/api/thermostat")
async def api_thermostat():
    return JSONResponse(await nest_get_thermostat())


@app.get("/api/doorbell")
async def api_doorbell():
    return JSONResponse(await nest_get_doorbell_events())


@app.get("/api/nest/auth")
async def api_nest_auth_start():
    if not NEST_CLIENT_ID or not NEST_PROJECT_ID:
        return JSONResponse({"error": "Nest not configured -- set NEST_PROJECT_ID and NEST_CLIENT_ID in .env"}, status_code=400)
    redirect_uri = f"http://{SERVER_HOST}:{SERVER_PORT}/api/nest/callback"
    url = (
        f"https://nestservices.google.com/partnerconnections/{NEST_PROJECT_ID}/auth"
        f"?redirect_uri={redirect_uri}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&client_id={NEST_CLIENT_ID}"
        f"&response_type=code"
        f"&scope=https://www.googleapis.com/auth/sdm.service"
    )
    return JSONResponse({"auth_url": url})


@app.get("/api/nest/callback")
async def api_nest_callback(code: str = Query(...)):
    global nest_access_token, nest_token_expiry
    redirect_uri = f"http://{SERVER_HOST}:{SERVER_PORT}/api/nest/callback"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": NEST_CLIENT_ID,
                "client_secret": NEST_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if r.status_code == 200:
            data = r.json()
            nest_access_token = data["access_token"]
            nest_token_expiry = time.time() + data.get("expires_in", 3600) - 60
            refresh = data.get("refresh_token", "")
            if refresh:
                env_path = os.path.join(os.path.dirname(__file__), ".env")
                with open(env_path, "r") as f:
                    lines = f.readlines()
                with open(env_path, "w") as f:
                    for line in lines:
                        if line.startswith("NEST_REFRESH_TOKEN="):
                            f.write(f"NEST_REFRESH_TOKEN={refresh}\n")
                        elif line.startswith("NEST_ACCESS_TOKEN="):
                            f.write(f"NEST_ACCESS_TOKEN={nest_access_token}\n")
                        else:
                            f.write(line)
            return HTMLResponse("<html><body style='background:#1a1a2e;color:#0f0;font-family:monospace;padding:40px'><h2>Nest authorized successfully!</h2><p>You can close this tab and return to the dashboard.</p></body></html>")
        return JSONResponse({"error": r.text}, status_code=400)


@app.get("/api/sensors")
async def api_sensors():
    nodes = await zwave_get_nodes()
    if not nodes:
        return JSONResponse({"sensors": {}, "nodes": []})

    sensor_nodes = []
    for n in nodes:
        if n.get("isControllerNode"):
            continue
        node_info = {
            "id": n["id"],
            "name": n.get("name", f"Node {n['id']}"),
            "location": n.get("loc", ""),
            "status": n.get("status", "Unknown"),
            "ready": n.get("ready", False),
            "manufacturer": n.get("manufacturer", ""),
            "productLabel": n.get("productLabel", ""),
            "battery": None,
            "doorOpen": None,
        }
        for vid, val in n.get("values", {}).items():
            cc_name = val.get("commandClassName", "")
            prop = val.get("property", "")
            if cc_name == "Battery" and prop == "level":
                node_info["battery"] = val.get("value")
            elif cc_name in ("Binary Sensor", "Notification"):
                if prop in ("Any", "Access Control", "sensorState"):
                    node_info["doorOpen"] = bool(val.get("value"))
        sensor_nodes.append(node_info)

    return JSONResponse({"sensors": zwave_sensors, "nodes": sensor_nodes})


# --- Weather (PWS via Weather Underground) ---
weather_cache = {}
weather_cache_time = 0

@app.get("/api/weather")
async def api_weather():
    global weather_cache, weather_cache_time
    now = time.time()
    if weather_cache and now - weather_cache_time < 300:
        return JSONResponse(weather_cache)
    if not WU_STATION_ID:
        return JSONResponse({"error": "WU_STATION_ID not configured in .env"})
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.weather.com/v2/pws/observations/current",
                params={
                    "stationId": WU_STATION_ID,
                    "format": "json",
                    "units": "e",
                    "apiKey": WU_API_KEY,
                },
            )
            if r.status_code == 200:
                data = r.json()
                obs = data.get("observations", [{}])[0]
                imperial = obs.get("imperial", {})
                weather_cache = {
                    "stationId": obs.get("stationID"),
                    "neighborhood": obs.get("neighborhood", ""),
                    "temp_f": imperial.get("temp"),
                    "humidity": obs.get("humidity"),
                    "windSpeed": imperial.get("windSpeed"),
                    "windGust": imperial.get("windGust"),
                    "windDir": obs.get("winddir"),
                    "pressure": imperial.get("pressure"),
                    "precipRate": imperial.get("precipRate"),
                    "precipTotal": imperial.get("precipTotal"),
                    "dewpt": imperial.get("dewpt"),
                    "heatIndex": imperial.get("heatIndex"),
                    "windChill": imperial.get("windChill"),
                    "uv": obs.get("uv"),
                    "solarRadiation": obs.get("solarRadiation"),
                    "updated": obs.get("obsTimeLocal", ""),
                }
                weather_cache_time = now
                return JSONResponse(weather_cache)
    except Exception as e:
        print(f"Weather error: {e}")
    return JSONResponse(weather_cache if weather_cache else {"error": "Weather unavailable"})


# --- Radar proxy (avoid CORS) ---
@app.get("/api/radar")
async def api_radar():
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"https://radar.weather.gov/ridge/standard/{RADAR_STATION}_loop.gif")
            if r.status_code == 200:
                return Response(content=r.content, media_type="image/gif")
    except Exception:
        pass
    return JSONResponse({"error": "Radar unavailable"}, status_code=502)


# --- HLS Grid Stream (for Roku) ---
@app.get("/api/hls/{filename}")
async def api_hls(filename: str):
    path = f"/tmp/hls/{filename}"
    if filename.endswith(".m3u8"):
        return FileResponse(path, media_type="application/vnd.apple.mpegurl")
    elif filename.endswith(".ts"):
        return FileResponse(path, media_type="video/mp2t")
    return JSONResponse({"error": "Not found"}, status_code=404)


# --- TV Screenshot (for Roku screensaver fallback) ---
@app.get("/api/tv-screenshot")
async def api_tv_screenshot():
    try:
        with open("/tmp/tv-dashboard.jpg", "rb") as f:
            return Response(content=f.read(), media_type="image/jpeg")
    except FileNotFoundError:
        return JSONResponse({"error": "Screenshot not ready"}, status_code=503)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)


@app.get("/api/status")
async def api_status():
    return JSONResponse({
        "unifi_connected": unifi_cookies is not None,
        "nest_configured": bool(NEST_PROJECT_ID and NEST_CLIENT_ID),
        "nest_authorized": bool(nest_access_token),
        "zwave_sensors": len(zwave_sensors),
        "ws_clients": len(ws_clients),
    })


# Static files + SPA fallback
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(SERVER_PORT))
