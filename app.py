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

# --- UniFi Network Stats ---
unifi_net_cache_data = {}
unifi_net_cache_ts = 0

@app.get("/api/network")
async def api_network_stats():
    global unifi_net_cache_data, unifi_net_cache_ts
    import time as _t
    if unifi_net_cache_data and _t.time() - unifi_net_cache_ts < 15:
        return unifi_net_cache_data
    import ssl, json as _j
    from urllib.request import Request
    from http.cookiejar import CookieJar
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()),
        urllib.request.HTTPSHandler(context=ctx))
    ld = _j.dumps({"username": UNIFI_USERNAME, "password": UNIFI_PASSWORD}).encode()
    opener.open(Request(f"https://{UNIFI_HOST}/api/auth/login", data=ld, headers={"Content-Type": "application/json"}))
    hd = _j.loads(opener.open(Request(f"https://{UNIFI_HOST}/proxy/network/api/s/default/stat/health")).read()).get("data", [])
    wan = next((d for d in hd if d.get("subsystem") == "wan"), {})
    wlan = next((d for d in hd if d.get("subsystem") == "wlan"), {})
    wd = _j.loads(opener.open(Request(f"https://{UNIFI_HOST}/proxy/network/api/s/default/rest/wlanconf")).read()).get("data", [])
    guest = next((w for w in wd if "guest" in w.get("name", "").lower()), {})
    ws = wan.get("uptime_stats", {}).get("WAN", {})
    gs = wan.get("gw_system-stats", {})
    # Get dual WAN details from device stats
    wan1_info = {}
    wan2_info = {}
    try:
        devs = _j.loads(opener.open(Request(f"https://{UNIFI_HOST}/proxy/network/api/s/default/stat/device")).read()).get("data", [])
        for dev in devs:
            lw = dev.get("last_wan_interfaces", {})
            lws = dev.get("last_wan_status", {})
            w1 = dev.get("wan1", {})
            w2 = dev.get("wan2", {})
            if lw:
                wan1_info = {"ip": lw.get("WAN",{}).get("ip",""), "status": lws.get("WAN","unknown"), "latency": w1.get("latency",0)}
                wan2_info = {"ip": lw.get("WAN2",{}).get("ip",""), "status": lws.get("WAN2","unknown"), "latency": w2.get("latency",0)}
                break
    except:
        pass
    unifi_net_cache_data = {
        "wan_status": wan.get("status", "unknown"),
        "wan1_ip": wan1_info.get("ip", ""), "wan1_status": wan1_info.get("status", "unknown"), "wan1_latency": wan1_info.get("latency", 0),
        "wan2_ip": wan2_info.get("ip", ""), "wan2_status": wan2_info.get("status", "unknown"), "wan2_latency": wan2_info.get("latency", 0),
        "isp": wan.get("isp_name", ""), "tx_bps": wan.get("tx_bytes-r", 0),
        "rx_bps": wan.get("rx_bytes-r", 0), "latency": ws.get("latency_average", 0),
        "availability": ws.get("availability", 0), "clients": wan.get("num_sta", 0),
        "wifi_clients": wlan.get("num_user", 0), "guests": wlan.get("num_guest", 0),
        "gw_cpu": gs.get("cpu", "0"), "gw_mem": gs.get("mem", "0"),
        "guest_ssid": guest.get("name", ""), "guest_pass": guest.get("x_passphrase", ""),
        "guest_security": "WPA" if guest.get("security") == "wpapsk" else guest.get("security", ""),
    }
    unifi_net_cache_ts = _t.time()
    return unifi_net_cache_data


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
            elif cc_name == "Binary Sensor":
                if prop in ("Any", "sensorState"):
                    node_info["doorOpen"] = bool(val.get("value"))
            elif cc_name == "Notification" and prop == "Access Control":
                pk = val.get("propertyKey", "")
                if pk in ("Door state", "Door state (simple)"):
                    # Aeotec/Vision sensors: 22=open, 23=closed
                    v = val.get("value")
                    if v == 22:
                        node_info["doorOpen"] = True
                    elif v == 23:
                        node_info["doorOpen"] = False
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
    # Try Weather Underground first (has UV, solar, precip)
    wu_key = os.getenv("WU_API_KEY", "")
    wu_station = os.getenv("WU_STATION_ID", "")
    if wu_key and wu_station:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://api.weather.com/v2/pws/observations/current",
                    params={"stationId": wu_station, "format": "json", "units": "e", "apiKey": wu_key},
                )
                if r.status_code == 200:
                    data = r.json()
                    obs = data.get("observations", [{}])[0]
                    imperial = obs.get("imperial", {})
                    weather_cache = {
                        "station": obs.get("stationID", wu_station),
                        "temp_f": imperial.get("temp"),
                        "humidity": obs.get("humidity"),
                        "windSpeed": imperial.get("windSpeed"),
                        "windGust": imperial.get("windGust"),
                        "windDir": obs.get("winddir"),
                        "pressure": imperial.get("pressure"),
                        "precipRate": imperial.get("precipRate"),
                        "precipTotal": imperial.get("precipTotal"),
                        "dewpt_f": imperial.get("dewpt"),
                        "uv": obs.get("uv"),
                        "solarRadiation": obs.get("solarRadiation"),
                        "updated": obs.get("obsTimeLocal", ""),
                    }
                    weather_cache_time = now
                    return JSONResponse(weather_cache)
        except Exception as e:
            print(f"WU weather error: {e}")
    # Fallback to NWS (free, no key)
    nws_station = os.getenv("NWS_STATION", "KRDU")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://api.weather.gov/stations/{nws_station}/observations/latest",
                headers={"User-Agent": "HomeMonitor/1.0"},
            )
            if r.status_code == 200:
                props = r.json().get("properties", {})
                def c2f(c):
                    return round(c * 9/5 + 32, 1) if c is not None else None
                def kph2mph(k):
                    return round(k * 0.621371) if k is not None else 0
                def pa2inhg(p):
                    return round(p * 0.00029530, 2) if p is not None else None
                weather_cache = {
                    "station": nws_station,
                    "temp_f": c2f(props.get("temperature", {}).get("value")),
                    "humidity": round(props.get("relativeHumidity", {}).get("value") or 0),
                    "windSpeed": kph2mph(props.get("windSpeed", {}).get("value")),
                    "windGust": kph2mph(props.get("windGust", {}).get("value")),
                    "windDir": props.get("windDirection", {}).get("value", 0),
                    "pressure": pa2inhg(props.get("barometricPressure", {}).get("value")),
                    "dewpt_f": c2f(props.get("dewpoint", {}).get("value")),
                    "precipTotal": 0, "precipRate": 0, "uv": 0, "solarRadiation": 0,
                    "updated": props.get("timestamp", ""),
                }
                weather_cache_time = now
                return JSONResponse(weather_cache)
    except Exception as e:
        print(f"NWS weather error: {e}")
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
    import os
    path = f"/tmp/hls/{filename}"
    if not os.path.exists(path):
        return JSONResponse({"error": "Not found"}, status_code=404)
    if filename.endswith(".m3u8"):
        return FileResponse(path, media_type="application/vnd.apple.mpegurl",
                          headers={"Cache-Control": "no-cache, no-store"})
    elif filename.endswith(".ts"):
        return FileResponse(path, media_type="video/mp2t",
                          headers={"Cache-Control": "max-age=3600"})
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


# network endpoint moved above
# (removed from here)
async def _dead_network():
    global unifi_net_cache, unifi_net_cache_time
    import time as _time
    if unifi_net_cache and _time.time() - unifi_net_cache_time < 15:
        return unifi_net_cache
    import ssl, json as _json
    from urllib.request import Request
    from http.cookiejar import CookieJar
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()),
        urllib.request.HTTPSHandler(context=ctx))
    login_data = _json.dumps({"username": UNIFI_USERNAME, "password": UNIFI_PASSWORD}).encode()
    login_req = Request(f"https://{UNIFI_HOST}/api/auth/login", data=login_data, headers={"Content-Type": "application/json"})
    opener.open(login_req)
    hdata = _json.loads(opener.open(Request(f"https://{UNIFI_HOST}/proxy/network/api/s/default/stat/health")).read()).get("data", [])
    wan = next((d for d in hdata if d.get("subsystem") == "wan"), {})
    wlan = next((d for d in hdata if d.get("subsystem") == "wlan"), {})
    wlan_data = _json.loads(opener.open(Request(f"https://{UNIFI_HOST}/proxy/network/api/s/default/rest/wlanconf")).read()).get("data", [])
    guest = next((w for w in wlan_data if w.get("is_guest")), {})
    wan_stats = wan.get("uptime_stats", {}).get("WAN", {})
    gw_stats = wan.get("gw_system-stats", {})
    unifi_net_cache = {
        "wan_status": wan.get("status", "unknown"),
        "wan_ip": wan.get("wan_ip", ""),
        "isp": wan.get("isp_name", ""),
        "tx_bps": wan.get("tx_bytes-r", 0),
        "rx_bps": wan.get("rx_bytes-r", 0),
        "latency": wan_stats.get("latency_average", 0),
        "availability": wan_stats.get("availability", 0),
        "clients": wan.get("num_sta", 0),
        "wifi_clients": wlan.get("num_user", 0),
        "guests": wlan.get("num_guest", 0),
        "gw_cpu": gw_stats.get("cpu", "0"),
        "gw_mem": gw_stats.get("mem", "0"),
        "guest_ssid": guest.get("name", ""),
        "guest_pass": guest.get("x_passphrase", ""),
        "guest_security": "WPA" if guest.get("security") == "wpapsk" else guest.get("security", ""),
    }
    unifi_net_cache_time = _time.time()
    return unifi_net_cache


# --- Z-Wave Door Sensor / Lock Status ---
@app.get("/api/doors")
async def api_doors():
    """Read door sensor and lock states from Z-Wave JS UI store."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "exec", "zwave-js-ui", "cat",
             "/usr/src/app/store/dca8c747.values.jsonl"],
            capture_output=True, text=True, timeout=5
        )
        names = {}
        states = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                rec = json.loads(line)
                k = json.loads(rec["k"])
                v = rec["v"]
                nid = k["nodeId"]
                cc = k["commandClass"]
                prop = k["property"]
                if cc == 119 and prop == "name":
                    names[nid] = v
                if cc == 48 and prop == "Any":
                    states.setdefault(nid, {})["open"] = v
                if cc == 113 and prop == "Access Control":
                    states.setdefault(nid, {})["access"] = v
                if cc == 98 and prop == "currentMode":
                    states.setdefault(nid, {})["lockMode"] = v
                if cc == 98 and prop == "doorStatus":
                    states.setdefault(nid, {})["doorStatus"] = v
                if cc == 98 and prop == "boltStatus":
                    states.setdefault(nid, {})["boltStatus"] = v
                if cc == 128 and prop == "level":
                    states.setdefault(nid, {})["battery"] = v
            except Exception:
                continue
        doors = []
        for nid in sorted(set(list(names.keys()) + list(states.keys()))):
            if nid == 1:
                continue
            name = names.get(nid, f"Node {nid}")
            s = states.get(nid, {})
            door = {"name": name, "nodeId": nid}
            if "open" in s:
                door["state"] = "open" if s["open"] else "closed"
            elif "access" in s:
                door["state"] = "open" if s["access"] == 22 else ("closed" if s["access"] == 23 else "unknown")
            elif "doorStatus" in s:
                door["state"] = s["doorStatus"]
            if "lockMode" in s:
                door["locked"] = s["lockMode"] == 255
                door["boltStatus"] = s.get("boltStatus", "unknown")
            if "battery" in s:
                door["battery"] = s["battery"]
            doors.append(door)
        return JSONResponse(doors)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- Kwikset Lock Status ---
kwikset_cache_data = {}
kwikset_cache_ts = 0

@app.get("/api/kwikset")
async def api_kwikset():
    global kwikset_cache_data, kwikset_cache_ts
    import time as _t
    now = _t.time()
    if kwikset_cache_data and now - kwikset_cache_ts < 30:
        return JSONResponse(kwikset_cache_data)
    try:
        import aiohttp
        from aiokwikset import API
        tokens = json.load(open("/home/swg/kwikset_tokens.json"))

        async def _update_tokens(new_tokens):
            with open("/home/swg/kwikset_tokens.json", "w") as f:
                json.dump(new_tokens, f)

        async with aiohttp.ClientSession() as session:
            api = API(
                websession=session,
                id_token=tokens["id_token"],
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                token_update_callback=_update_tokens,
            )
            await api.async_renew_access_token()
            homes = await api.user.get_homes()
            devices = []
            for h in homes:
                devs = await api.device.get_devices(h["homeid"])
                for d in devs:
                    devices.append({
                        "devicename": d.get("devicename", "Lock"),
                        "lockstatus": d.get("lockstatus", "Unknown"),
                        "batterypercentage": d.get("batterypercentage"),
                        "batterystatus": d.get("batterystatus", ""),
                        "doorstatus": d.get("doorstatus", ""),
                        "doorsettings": d.get("doorsettings", ""),
                        "connected": d.get("deviceconnectivitystatus") == "connected",
                    })
            kwikset_cache_data = {"devices": devices, "updated": now}
            kwikset_cache_ts = now
            return JSONResponse(kwikset_cache_data)
    except Exception as e:
        print(f"Kwikset API error: {e}")
        if kwikset_cache_data:
            return JSONResponse(kwikset_cache_data)
        return JSONResponse({"error": str(e), "devices": []}, status_code=500)



# --- 7-Day Forecast (NWS + sunrise/sunset) ---
forecast_cache = {}
forecast_cache_time = 0

async def _fetch_forecast():
    global forecast_cache, forecast_cache_time
    now = time.time()
    if forecast_cache and now - forecast_cache_time < 1800:
        return forecast_cache

    NWS_GRID_URL = "https://api.weather.gov/gridpoints/YOUR_NWS_OFFICE/YOUR_GRID_X,YOUR_GRID_Y/forecast"
    SUNRISESET_URL = "https://api.sunrise-sunset.org/json?lat=YOUR_LAT&lng=YOUR_LON&formatted=0"

    periods = []
    sunrise = sunset = ""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            nws_r = await client.get(NWS_GRID_URL, headers={"User-Agent": "HomeMonitor/1.0"})
            if nws_r.status_code == 200:
                raw_periods = nws_r.json().get("properties", {}).get("periods", [])
                periods = raw_periods

            sun_r = await client.get(SUNRISESET_URL)
            if sun_r.status_code == 200:
                sun_data = sun_r.json().get("results", {})
                sunrise = sun_data.get("sunrise", "")
                sunset = sun_data.get("sunset", "")
    except Exception as e:
        print(f"Forecast fetch error: {e}")
        if forecast_cache:
            return forecast_cache
        return {"error": "Forecast unavailable"}

    # Convert sunrise/sunset to local time
    from datetime import datetime as _dt
    def _utc_to_local(iso_str):
        if not iso_str:
            return ""
        try:
            from zoneinfo import ZoneInfo
            utc_dt = _dt.fromisoformat(iso_str.replace("Z", "+00:00"))
            local_dt = utc_dt.astimezone(ZoneInfo("America/New_York"))
            return local_dt.strftime("%-I:%M %p")
        except Exception:
            return iso_str

    sunrise_local = _utc_to_local(sunrise)
    sunset_local = _utc_to_local(sunset)

    # Pair day+night periods
    paired = []
    i = 0
    while i < len(periods):
        p = periods[i]
        precip_pct = 0
        pop = p.get("probabilityOfPrecipitation", {})
        if pop and pop.get("value") is not None:
            precip_pct = pop["value"]

        entry = {
            "name": p.get("name", ""),
            "shortForecast": p.get("shortForecast", ""),
            "precipChance": precip_pct,
        }

        if p.get("isDaytime"):
            entry["hi"] = p.get("temperature")
            # Check if next period is the matching night
            if i + 1 < len(periods) and not periods[i + 1].get("isDaytime"):
                night = periods[i + 1]
                entry["lo"] = night.get("temperature")
                night_pop = night.get("probabilityOfPrecipitation", {})
                if night_pop and night_pop.get("value") is not None:
                    entry["precipChance"] = max(precip_pct, night_pop["value"])
                entry["nightForecast"] = night.get("shortForecast", "")
                i += 2
            else:
                entry["lo"] = None
                i += 1
        else:
            # Starts with a night period (e.g. fetched in the evening)
            entry["lo"] = p.get("temperature")
            entry["hi"] = None
            i += 1

        paired.append(entry)

    forecast_cache = {
        "periods": paired,
        "sunrise": sunrise_local,
        "sunset": sunset_local,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    forecast_cache_time = time.time()
    return forecast_cache


@app.get("/api/forecast")
async def api_forecast():
    data = await _fetch_forecast()
    return JSONResponse(data)


# --- Radar as PNG (last frame) ---
radar_png_cache = b""
radar_png_cache_time = 0

@app.get("/api/radar.png")
async def api_radar_png():
    global radar_png_cache, radar_png_cache_time
    now = time.time()
    if radar_png_cache and now - radar_png_cache_time < 300:
        return Response(content=radar_png_cache, media_type="image/png")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(f"https://radar.weather.gov/ridge/standard/{RADAR_STATION}_loop.gif")
            if r.status_code != 200:
                return JSONResponse({"error": "Radar unavailable"}, status_code=502)

        from PIL import Image
        import io
        gif = Image.open(io.BytesIO(r.content))
        # Seek to last frame
        try:
            while True:
                gif.seek(gif.tell() + 1)
        except EOFError:
            pass  # now on last frame
        buf = io.BytesIO()
        gif.save(buf, format="PNG")
        radar_png_cache = buf.getvalue()
        radar_png_cache_time = now
        return Response(content=radar_png_cache, media_type="image/png")
    except Exception as e:
        print(f"Radar PNG error: {e}")
        return JSONResponse({"error": f"Radar unavailable: {e}"}, status_code=502)


# --- Guest WiFi QR Code ---
guest_qr_cache = b""
guest_qr_cache_time = 0

@app.get("/api/guest-wifi-qr.png")
async def api_guest_wifi_qr():
    global guest_qr_cache, guest_qr_cache_time
    now = time.time()
    if guest_qr_cache and now - guest_qr_cache_time < 3600:
        return Response(content=guest_qr_cache, media_type="image/png")

    try:
        net_data = await api_network_stats()
        if isinstance(net_data, dict):
            net = net_data
        else:
            net = net_data.body if hasattr(net_data, "body") else {}
            if isinstance(net, bytes):
                net = json.loads(net)

        ssid = net.get("guest_ssid", "")
        password = net.get("guest_pass", "")
        if not ssid:
            return JSONResponse({"error": "Guest WiFi not configured"}, status_code=404)

        import qrcode, io
        wifi_str = f"WIFI:T:WPA;S:{ssid};P:{password};;"
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
        qr.add_data(wifi_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        guest_qr_cache = buf.getvalue()
        guest_qr_cache_time = now
        return Response(content=guest_qr_cache, media_type="image/png")
    except Exception as e:
        print(f"QR code error: {e}")
        return JSONResponse({"error": f"QR generation failed: {e}"}, status_code=500)


# --- Consolidated Dashboard ---
@app.get("/api/dashboard")
async def api_dashboard():
    import asyncio as _aio
    results = {}
    async def _safe(name, coro):
        try:
            r = await coro
            if hasattr(r, "body"):
                results[name] = json.loads(r.body)
            elif isinstance(r, dict):
                results[name] = r
            else:
                results[name] = r
        except Exception as e:
            results[name] = {"error": str(e)}

    await _aio.gather(
        _safe("weather", api_weather()),
        _safe("forecast", _fetch_forecast()),
        _safe("thermostat", nest_get_thermostat()),
        _safe("sensors", api_sensors()),
        _safe("kwikset", api_kwikset()),
        _safe("network", api_network_stats()),
        _safe("doors", api_doors()),
        _safe("vehicle", api_vehicle()),
    )
    return JSONResponse(results)




@app.get("/api/panel-strip.png")
async def api_panel_strip():
    try:
        with open("/tmp/panel_strip.png", "rb") as f:
            return Response(content=f.read(), media_type="image/png")
    except Exception:
        return JSONResponse({"error": "Panel strip not ready"}, status_code=503)



# --- Vehicle Telemetry ---
vehicle_cache = {}
vehicle_cache_time = 0

@app.get("/api/vehicle")
async def api_vehicle():
    global vehicle_cache, vehicle_cache_time
    now = time.time()
    if vehicle_cache and now - vehicle_cache_time < 120:  # 2 min cache
        return JSONResponse(vehicle_cache)

    result = {"jeep": {}, "rav4": {}}

    # Samsara data (GPS, fuel, engine state)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.samsara.com/fleet/vehicles/stats",
                params={"types": "gps,fuelPercents,engineStates,obdOdometerMeters"},
                headers={"Authorization": "Bearer YOUR_SAMSARA_TOKEN"}
            )
            if r.status_code == 200:
                for v in r.json().get("data", []):
                    name = v.get("name", "")
                    gps = v.get("gps", {})
                    entry = {
                        "location": gps.get("reverseGeo", {}).get("formattedLocation", ""),
                        "lat": gps.get("latitude"),
                        "lon": gps.get("longitude"),
                        "speed": gps.get("speedMilesPerHour", 0),
                        "engine": v.get("engineState", {}).get("value", "Unknown"),
                        "fuel_pct": v.get("fuelPercent", {}).get("value"),
                        "odometer_mi": round(v.get("obdOdometerMeters", {}).get("value", 0) * 0.000621371, 1),
                    }
                    if "Jeep" in name and "VG" in name:
                        result["jeep"].update(entry)
                    elif "RAV4" in name or "Toyota" in name:
                        result["rav4"].update(entry)
    except Exception as e:
        print(f"Samsara error: {e}")

    # py-uconnect data (EV, tires, charging) - run in thread to avoid blocking
    try:
        uconnect_data = await asyncio.get_event_loop().run_in_executor(None, _get_uconnect_data)
        if uconnect_data:
            result["jeep"].update(uconnect_data)
    except Exception as e:
        print(f"Uconnect error: {e}")

    vehicle_cache = result
    vehicle_cache_time = now
    return JSONResponse(result)

def _get_uconnect_data():
    """Sync function to get py-uconnect data (runs in thread pool)."""
    try:
        from py_uconnect import brands, Client
        client = Client(
            os.getenv("UCONNECT_EMAIL", "YOUR_UCONNECT_EMAIL"),
            os.getenv("UCONNECT_PASSWORD", "YOUR_UCONNECT_PASSWORD"),
            pin=os.getenv("UCONNECT_PIN", "YOUR_UCONNECT_PIN"),
            brand=brands.JEEP_US
        )
        client.refresh()
        vehicles = client.get_vehicles()
        # Pick the vehicle with the most recent timestamp (API returns dupes)
        best_v = None
        best_ts = None
        for vin, v in vehicles.items():
            ts = v.timestamp_info
            if best_ts is None or (ts and str(ts) > str(best_ts)):
                best_v = v
                best_ts = ts
        if best_v is None:
            return None
        v = best_v
        def kpa_to_psi(kpa):
            return round(kpa * 0.145038, 1) if kpa else None
        return {
                "ev_soc": v.state_of_charge,
                "ev_charging": v.charging,
                "ev_charging_level": v.charging_level,
                "ev_plugged_in": v.plugged_in,
                "ev_range_km": v.distance_to_empty,
                "ev_range_mi": round(v.distance_to_empty * 0.621371) if v.distance_to_empty else None,
                "total_range_km": v.range_total,
                "total_range_mi": round(v.range_total * 0.621371) if v.range_total else None,
                "time_to_full_l1": v.time_to_fully_charge_l1,
                "time_to_full_l2": v.time_to_fully_charge_l2,
                "battery_voltage": v.battery_voltage,
                "oil_level": v.oil_level,
                "ignition": v.ignition_on,
                "tire_fl_psi": kpa_to_psi(v.wheel_front_left_pressure),
                "tire_fr_psi": kpa_to_psi(v.wheel_front_right_pressure),
                "tire_rl_psi": kpa_to_psi(v.wheel_rear_left_pressure),
                "tire_rr_psi": kpa_to_psi(v.wheel_rear_right_pressure),
                "tire_fl_warn": v.wheel_front_left_pressure_warning,
                "tire_fr_warn": v.wheel_front_right_pressure_warning,
                "tire_rl_warn": v.wheel_rear_left_pressure_warning,
                "tire_rr_warn": v.wheel_rear_right_pressure_warning,
            }
    except Exception as e:
        print(f"Uconnect fetch error: {e}")
        return None


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(SERVER_PORT))
