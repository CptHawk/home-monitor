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

LEVITON_EMAIL = os.getenv("LEVITON_EMAIL", "")
LEVITON_PASSWORD = os.getenv("LEVITON_PASSWORD", "")

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

leviton_session = None
leviton_devices_cache = []
leviton_cache_time = 0

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
# Leviton Decora Smart WiFi helpers (cloud API via decora_wifi)
# ---------------------------------------------------------------------------
def _leviton_login_sync():
    """Log in to Leviton cloud. Returns session or None."""
    global leviton_session
    if not LEVITON_EMAIL or not LEVITON_PASSWORD:
        return None
    try:
        from decora_wifi import DecoraWiFiSession
        session = DecoraWiFiSession()
        session.login(LEVITON_EMAIL, LEVITON_PASSWORD)
        leviton_session = session
        return session
    except Exception as e:
        print(f"Leviton login error: {e}")
        return None


def _leviton_get_session_sync():
    global leviton_session
    if leviton_session is not None:
        return leviton_session
    return _leviton_login_sync()


def _leviton_get_devices_sync():
    """Fetch all Leviton switches/dimmers. Returns list of dicts."""
    global leviton_devices_cache, leviton_cache_time
    now = time.time()
    if leviton_devices_cache and now - leviton_cache_time < 30:
        return leviton_devices_cache

    session = _leviton_get_session_sync()
    if not session:
        return []

    try:
        from decora_wifi.models.residential_account import ResidentialAccount
        devices = []
        perms = session.user.get_residential_permissions()
        for perm in perms:
            acct = ResidentialAccount(session, perm.residentialAccountId)
            for residence in acct.get_residences():
                for switch in residence.get_iot_switches():
                    devices.append({
                        "id": switch.id,
                        "name": switch.name,
                        "power": getattr(switch, "power", "OFF"),
                        "brightness": getattr(switch, "brightness", None),
                        "canSetLevel": switch.canSetLevel if hasattr(switch, "canSetLevel") else False,
                        "_switch": switch,
                    })
        leviton_devices_cache = devices
        leviton_cache_time = now
        return devices
    except Exception as e:
        print(f"Leviton devices error: {e}")
        # Session may have expired, clear it
        leviton_session = None
        return []


def _leviton_set_switch_sync(device_id, power=None, brightness=None):
    """Control a Leviton switch/dimmer."""
    devices = _leviton_get_devices_sync()
    for d in devices:
        if str(d["id"]) == str(device_id):
            switch = d["_switch"]
            attrs = {}
            if power is not None:
                attrs["power"] = power
            if brightness is not None:
                attrs["brightness"] = max(0, min(100, brightness))
            try:
                switch.update_attributes(attrs)
                # Invalidate cache
                global leviton_cache_time
                leviton_cache_time = 0
                return True
            except Exception as e:
                print(f"Leviton set error: {e}")
                return False
    return False


async def leviton_get_devices():
    return await asyncio.to_thread(_leviton_get_devices_sync)


async def leviton_set_switch(device_id, power=None, brightness=None):
    return await asyncio.to_thread(_leviton_set_switch_sync, device_id, power, brightness)


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


# --- Leviton Lights ---
@app.get("/api/lights")
async def api_lights():
    devices = await leviton_get_devices()
    return JSONResponse([
        {
            "id": d["id"],
            "name": d["name"],
            "power": d["power"],
            "brightness": d["brightness"],
            "canSetLevel": d["canSetLevel"],
        }
        for d in devices
    ])


@app.post("/api/lights/{device_id}/toggle")
async def api_light_toggle(device_id: str):
    devices = await leviton_get_devices()
    for d in devices:
        if str(d["id"]) == device_id:
            new_power = "OFF" if d["power"] == "ON" else "ON"
            ok = await leviton_set_switch(device_id, power=new_power)
            if ok:
                return JSONResponse({"success": True, "power": new_power})
            return JSONResponse({"error": "Failed to toggle"}, status_code=502)
    return JSONResponse({"error": "Device not found"}, status_code=404)


@app.post("/api/lights/{device_id}/brightness")
async def api_light_brightness(device_id: str, level: int = Query(..., ge=0, le=100)):
    ok = await leviton_set_switch(device_id, brightness=level)
    if ok:
        return JSONResponse({"success": True, "brightness": level})
    return JSONResponse({"error": "Failed to set brightness"}, status_code=502)


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


# --- Roku Interactive API ---
@app.get("/api/roku/config")
async def api_roku_config():
    """Return camera list with individual stream URLs for Roku channel."""
    go2rtc_base = f"http://{SERVER_HOST}:{GO2RTC_PORT}"
    cameras = [
        {"name": "Camera 1", "key": "camera-1"},
        {"name": "Camera 2", "key": "camera-2"},
        {"name": "Camera 3", "key": "camera-3"},
        {"name": "Camera 4", "key": "camera-4"},
        {"name": "Nest Doorbell", "key": "nest-doorbell"},
    ]
    return JSONResponse({
        "grid_url": f"http://{SERVER_HOST}:{SERVER_PORT}/api/hls/grid.m3u8",
        "cameras": [
            {
                "name": c["name"],
                "stream_url": f"{go2rtc_base}/api/stream.m3u8?src={c['key']}",
            }
            for c in cameras
        ],
    })


@app.get("/api/roku/overlay")
async def api_roku_overlay():
    """Return weather + sensor summary for Roku info overlay."""
    weather = weather_cache.copy() if weather_cache else {}
    thermostat = thermostat_cache.copy() if thermostat_cache else {}

    sensor_list = []
    nodes = await zwave_get_nodes()
    if nodes:
        for n in nodes:
            if n.get("isControllerNode"):
                continue
            name = n.get("name", f"Node {n['id']}")
            door_open = None
            battery = None
            for vid, val in n.get("values", {}).items():
                cc_name = val.get("commandClassName", "")
                prop = val.get("property", "")
                if cc_name == "Battery" and prop == "level":
                    battery = val.get("value")
                elif cc_name in ("Binary Sensor", "Notification"):
                    if prop in ("Any", "Access Control", "sensorState"):
                        door_open = bool(val.get("value"))
            sensor_list.append({
                "name": name,
                "doorOpen": door_open,
                "battery": battery,
            })

    return JSONResponse({
        "weather": {
            "temp_f": weather.get("temp_f"),
            "humidity": weather.get("humidity"),
            "windSpeed": weather.get("windSpeed"),
            "windDir": weather.get("windDir"),
            "condition": weather.get("neighborhood", ""),
        },
        "thermostat": {
            "temp_f": thermostat.get("temperature_f"),
            "humidity": thermostat.get("humidity"),
            "mode": thermostat.get("mode"),
            "hvac_status": thermostat.get("hvac_status"),
            "heat_setpoint_c": thermostat.get("heat_setpoint_c"),
            "cool_setpoint_c": thermostat.get("cool_setpoint_c"),
        },
        "sensors": sensor_list,
        "lights": [
            {
                "id": d["id"],
                "name": d["name"],
                "power": d["power"],
                "brightness": d["brightness"],
                "canSetLevel": d["canSetLevel"],
            }
            for d in (await leviton_get_devices())
        ],
    })


@app.post("/api/roku/lights/{device_id}/toggle")
async def api_roku_light_toggle(device_id: str):
    """Toggle a Leviton light from the Roku remote."""
    devices = await leviton_get_devices()
    for d in devices:
        if str(d["id"]) == device_id:
            new_power = "OFF" if d["power"] == "ON" else "ON"
            ok = await leviton_set_switch(device_id, power=new_power)
            if ok:
                return JSONResponse({"success": True, "power": new_power})
            return JSONResponse({"error": "Failed to toggle"}, status_code=502)
    return JSONResponse({"error": "Device not found"}, status_code=404)


@app.post("/api/roku/lights/{device_id}/brightness")
async def api_roku_light_brightness(device_id: str, delta: int = Query(..., description="Brightness change, e.g. 10 or -10")):
    """Adjust a Leviton dimmer brightness from the Roku remote."""
    devices = await leviton_get_devices()
    for d in devices:
        if str(d["id"]) == device_id:
            current = d["brightness"] if d["brightness"] is not None else (100 if d["power"] == "ON" else 0)
            new_level = max(0, min(100, current + delta))
            ok = await leviton_set_switch(device_id, brightness=new_level)
            if ok:
                return JSONResponse({"success": True, "brightness": new_level})
            return JSONResponse({"error": "Failed to adjust"}, status_code=502)
    return JSONResponse({"error": "Device not found"}, status_code=404)


@app.post("/api/roku/thermostat/setpoint")
async def api_roku_thermostat_setpoint(delta_f: float = Query(..., description="Temperature change in F, e.g. 1 or -1")):
    """Adjust thermostat setpoint by delta degrees Fahrenheit."""
    device_id = None
    devices = await nest_get_devices()
    for d in devices:
        if "THERMOSTAT" in d.get("type", ""):
            device_id = d.get("name")
            break
    if not device_id:
        return JSONResponse({"error": "No thermostat found"}, status_code=404)

    token = await nest_get_token()
    if not token:
        return JSONResponse({"error": "Nest not authorized"}, status_code=401)

    traits = {}
    for d in devices:
        if d.get("name") == device_id:
            traits = d.get("traits", {})

    mode = traits.get("sdm.devices.traits.ThermostatMode", {}).get("mode", "OFF")
    setpoint = traits.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})

    delta_c = delta_f * 5 / 9

    if mode == "HEAT":
        current_c = setpoint.get("heatCelsius", 20)
        new_c = round(current_c + delta_c, 1)
        command = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetHeat"
        params = {"heatCelsius": new_c}
    elif mode == "COOL":
        current_c = setpoint.get("coolCelsius", 24)
        new_c = round(current_c + delta_c, 1)
        command = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetCool"
        params = {"coolCelsius": new_c}
    elif mode == "HEATCOOL":
        heat_c = setpoint.get("heatCelsius", 20)
        cool_c = setpoint.get("coolCelsius", 24)
        command = "sdm.devices.commands.ThermostatTemperatureSetpoint.SetRange"
        params = {"heatCelsius": round(heat_c + delta_c, 1), "coolCelsius": round(cool_c + delta_c, 1)}
    else:
        return JSONResponse({"error": "Thermostat is OFF"}, status_code=400)

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://smartdevicemanagement.googleapis.com/v1/{device_id}:executeCommand",
            headers={"Authorization": f"Bearer {token}"},
            json={"command": command, "params": params},
        )
        if r.status_code == 200:
            global thermostat_cache_time
            thermostat_cache_time = 0
            new_f = round(list(params.values())[0] * 9 / 5 + 32) if mode != "HEATCOOL" else None
            return JSONResponse({"success": True, "new_setpoint_f": new_f, "params": params})
        return JSONResponse({"error": r.text}, status_code=r.status_code)


@app.post("/api/roku/thermostat/mode")
async def api_roku_thermostat_mode(mode: str = Query(..., description="HEAT, COOL, HEATCOOL, or OFF")):
    """Set thermostat mode."""
    if mode not in ("HEAT", "COOL", "HEATCOOL", "OFF"):
        return JSONResponse({"error": "Invalid mode. Use HEAT, COOL, HEATCOOL, or OFF"}, status_code=400)

    device_id = None
    devices = await nest_get_devices()
    for d in devices:
        if "THERMOSTAT" in d.get("type", ""):
            device_id = d.get("name")
            break
    if not device_id:
        return JSONResponse({"error": "No thermostat found"}, status_code=404)

    token = await nest_get_token()
    if not token:
        return JSONResponse({"error": "Nest not authorized"}, status_code=401)

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://smartdevicemanagement.googleapis.com/v1/{device_id}:executeCommand",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "command": "sdm.devices.commands.ThermostatMode.SetMode",
                "params": {"mode": mode},
            },
        )
        if r.status_code == 200:
            global thermostat_cache_time
            thermostat_cache_time = 0
            return JSONResponse({"success": True, "mode": mode})
        return JSONResponse({"error": r.text}, status_code=r.status_code)


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
