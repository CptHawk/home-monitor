#!/usr/bin/env python3
"""Renders weather info + 7-day forecast as images for the ffmpeg grid stream."""
import json, time, os
from datetime import datetime
from urllib.request import urlopen, Request
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG = (13, 15, 20)
CARD_BG = (25, 28, 38)
ACCENT = (74, 158, 255)
GREEN = (76, 175, 80)
ORANGE = (255, 152, 0)
WHITE = (255, 255, 255)
GRAY = (170, 170, 170)
DIM = (100, 100, 100)

def fetch_json(url, timeout=5):
    try:
        req = Request(url, headers={"User-Agent": "HomeMonitor/1.0"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return None

def render_current_weather(width=360, height=340):
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(FONT_BOLD, 52)
    f_med = ImageFont.truetype(FONT_BOLD, 20)
    f_sm = ImageFont.truetype(FONT, 16)
    f_xs = ImageFont.truetype(FONT, 13)
    f_label = ImageFont.truetype(FONT_BOLD, 11)

    wx = fetch_json("http://127.0.0.1:8092/api/weather")
    thermo = fetch_json("http://127.0.0.1:8092/api/thermostat")

    temp = wx.get("temp_f", "?") if wx else "?"
    hum = wx.get("humidity", "?") if wx else "?"
    wind = wx.get("windSpeed", "0") if wx else "0"
    gust = wx.get("windGust", "0") if wx else "0"
    wind_dir = wx.get("windDir", "--") if wx else "--"
    rain = wx.get("precipTotal", "0.0") if wx else "0.0"
    rain_rate = wx.get("precipRate", "0.0") if wx else "0.0"
    uv = wx.get("uv", "0") if wx else "0"
    solar = wx.get("solarRadiation", "0") if wx else "0"
    pressure = wx.get("pressure", "?") if wx else "?"
    dewpoint = wx.get("dewpt_f", "?") if wx else "?"

    in_temp = thermo.get("temperature_f", "?") if thermo else "?"
    in_hum = thermo.get("humidity", "?") if thermo else "?"
    in_mode = (thermo.get("mode", "?") or "?").upper() if thermo else "?"
    in_hvac = (thermo.get("hvac_status", "?") or "?").upper() if thermo else "?"
    cool_c = thermo.get("cool_setpoint_c") if thermo else None
    heat_c = thermo.get("heat_setpoint_c") if thermo else None
    in_set = round(cool_c * 9/5 + 32) if cool_c else (round(heat_c * 9/5 + 32) if heat_c else "?")

    y = 8

    # OUTSIDE header
    draw.text((12, y), "OUTSIDE", fill=ACCENT, font=f_label)
    y += 16

    # Big temp
    draw.text((12, y), str(temp) + chr(176), fill=WHITE, font=f_big)

    # Right-side weather details
    rx = 160
    draw.text((rx, y+4), "Humidity", fill=DIM, font=f_xs)
    draw.text((rx+70, y+4), str(hum) + "%", fill=GRAY, font=f_sm)
    draw.text((rx, y+22), "Dewpoint", fill=DIM, font=f_xs)
    draw.text((rx+70, y+22), str(dewpoint) + chr(176) + "F", fill=GRAY, font=f_sm)
    draw.text((rx, y+40), "Pressure", fill=DIM, font=f_xs)
    draw.text((rx+70, y+40), str(pressure) + " inHg", fill=GRAY, font=f_sm)

    rx2 = 340
    draw.text((rx2, y+4), "Wind", fill=DIM, font=f_xs)
    draw.text((rx2+45, y+4), str(wind) + " mph " + str(wind_dir), fill=GRAY, font=f_sm)
    draw.text((rx2, y+22), "Gust", fill=DIM, font=f_xs)
    draw.text((rx2+45, y+22), str(gust) + " mph", fill=GRAY, font=f_sm)
    draw.text((rx2, y+40), "UV", fill=DIM, font=f_xs)
    uv_val = float(uv) if uv != "?" else 0
    uv_color = GREEN if uv_val < 3 else (ORANGE if uv_val < 6 else (255, 0, 0))
    draw.text((rx2+45, y+40), str(uv), fill=uv_color, font=f_sm)

    y += 70

    # Rain/solar bar
    draw.rounded_rectangle((12, y, width-12, y+32), radius=6, fill=CARD_BG)
    draw.text((20, y+6), "Rain", fill=DIM, font=f_xs)
    draw.text((55, y+6), str(rain_rate) + " in/hr", fill=GRAY, font=f_sm)
    draw.text((190, y+6), "Total", fill=DIM, font=f_xs)
    draw.text((230, y+6), str(rain) + " in", fill=GRAY, font=f_sm)
    draw.text((340, y+6), "Solar", fill=DIM, font=f_xs)
    draw.text((380, y+6), str(solar) + " W/m" + chr(178), fill=GRAY, font=f_sm)

    y += 44
    draw.line([(12, y), (width-12, y)], fill=DIM, width=1)
    y += 10

    # INSIDE section
    draw.text((12, y), "INSIDE", fill=ACCENT, font=f_label)
    draw.text((240, y), "THERMOSTAT", fill=DIM, font=f_label)
    y += 16

    draw.text((12, y), str(in_temp) + chr(176), fill=WHITE, font=f_big)

    draw.text((160, y+4), "Humidity", fill=DIM, font=f_xs)
    draw.text((230, y+4), str(in_hum) + "%", fill=GRAY, font=f_sm)
    mode_color = ACCENT if in_mode == "COOL" else ORANGE if in_mode == "HEAT" else GRAY
    draw.text((160, y+26), "Mode", fill=DIM, font=f_xs)
    draw.text((230, y+26), str(in_mode), fill=mode_color, font=f_sm)
    hvac_color = GREEN if in_hvac in ("COOLING", "HEATING") else GRAY
    draw.text((310, y+4), "HVAC", fill=DIM, font=f_xs)
    draw.text((365, y+4), str(in_hvac), fill=hvac_color, font=f_sm)
    draw.text((310, y+26), "Setpoint", fill=DIM, font=f_xs)
    draw.text((365, y+26), str(in_set) + chr(176) + "F", fill=WHITE, font=f_sm)

    y += 70
    draw.line([(12, y), (width-12, y)], fill=DIM, width=1)
    y += 10

    # DOORS
    draw.text((12, y), "DOORS", fill=ACCENT, font=f_label)
    y += 16

    RED = (255, 80, 80)
    door_x = 12
    sensors = fetch_json("http://127.0.0.1:8092/api/sensors")
    kwikset = fetch_json("http://127.0.0.1:8092/api/kwikset")

    def _tw(text, font):
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    # Build lookup dicts
    zw_nodes = {}
    if sensors and "nodes" in sensors:
        for node in sensors["nodes"]:
            zw_nodes[node.get("name", "")] = node

    kw_dev = None
    if kwikset and "devices" in kwikset and kwikset["devices"]:
        kw_dev = kwikset["devices"][0]

    # Ordered door lines: Front Door + Kwikset, Side Door, Sunroom Door + Yale Lock
    door_lines = [
        {"label": "Front Door", "sensor": zw_nodes.get("Front Door"), "lock": kw_dev, "lock_type": "kwikset"},
        {"label": "Side Door", "sensor": zw_nodes.get("Side Door"), "lock": None, "lock_type": None},
        {"label": "Sunroom", "sensor": zw_nodes.get("Sunroom Door"), "lock": zw_nodes.get("Sunroom Lock"), "lock_type": "yale"},
    ]

    for dl in door_lines:
        cx = door_x
        sensor = dl["sensor"]
        lock = dl["lock"]

        # Door sensor status
        if sensor:
            door_open = sensor.get("doorOpen", False)
            dot_color = RED if door_open else GREEN
            draw.ellipse((cx, y + 4, cx + 8, y + 12), fill=dot_color)
            cx += 14
            draw.text((cx, y), dl["label"], fill=WHITE, font=f_xs)
            cx += _tw(dl["label"], f_xs) + 6
            state_text = "OPEN" if door_open else "Closed"
            draw.text((cx, y), state_text, fill=RED if door_open else GREEN, font=f_xs)
            cx += _tw(state_text, f_xs) + 10
        else:
            cx += 14
            draw.text((cx, y), dl["label"], fill=DIM, font=f_xs)
            cx += _tw(dl["label"], f_xs) + 6
            draw.text((cx, y), "--", fill=DIM, font=f_xs)
            cx += 20

        # Lock status on same line
        if lock and dl["lock_type"] == "kwikset":
            lock_status = lock.get("lockstatus", "?")
            is_locked = lock_status.lower() == "locked"
            draw.text((cx, y), "|", fill=DIM, font=f_xs)
            cx += 10
            lock_color = GREEN if is_locked else RED
            draw.text((cx, y), lock_status, fill=lock_color, font=f_xs)
            cx += _tw(lock_status, f_xs) + 6
            batt = lock.get("batterypercentage")
            if batt is not None:
                batt_color = GREEN if batt > 30 else ORANGE if batt > 10 else RED
                draw.text((cx, y), str(batt) + "%", fill=batt_color, font=f_xs)
        elif lock and dl["lock_type"] == "yale":
            lock_open = lock.get("doorOpen", False)
            lock_status = "Unlocked" if lock_open else "Locked"
            is_locked = not lock_open
            draw.text((cx, y), "|", fill=DIM, font=f_xs)
            cx += 10
            lock_color = GREEN if is_locked else RED
            draw.text((cx, y), lock_status, fill=lock_color, font=f_xs)
            cx += _tw(lock_status, f_xs) + 6
            batt = lock.get("battery")
            if batt is not None:
                batt_color = GREEN if batt > 30 else ORANGE if batt > 10 else RED
                draw.text((cx, y), str(batt) + "%", fill=batt_color, font=f_xs)

        y += 14

    if not sensors and not kwikset:
        draw.text((12, y), "Sensors unavailable", fill=DIM, font=f_xs)

    # Clock bottom right
    now = datetime.now()
    draw.text((width-145, height-42), now.strftime("%I:%M %p"), fill=WHITE, font=f_med)
    draw.text((width-145, height-20), now.strftime("%A %b %d"), fill=DIM, font=f_xs)

    return img


def render_forecast(width=240, height=340):
    """Narrow 7-day forecast column."""
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    f_label = ImageFont.truetype(FONT_BOLD, 11)
    f_day = ImageFont.truetype(FONT_BOLD, 12)
    f_hi = ImageFont.truetype(FONT_BOLD, 14)
    f_lo = ImageFont.truetype(FONT, 12)
    f_sm = ImageFont.truetype(FONT, 10)
    f_xs = ImageFont.truetype(FONT, 9)
    f_icon = ImageFont.truetype(FONT, 22)

    data = fetch_json("https://api.weather.gov/gridpoints/YOUR_NWS_OFFICE/YOUR_GRID_X,YOUR_GRID_Y/forecast", timeout=10)
    if not data or "properties" not in data:
        draw.text((8, 8), "FORECAST", fill=ACCENT, font=f_label)
        draw.text((8, 24), "Loading...", fill=DIM, font=f_sm)
        return img

    periods = data["properties"]["periods"][:14]

    # Sunrise/sunset
    sunrise_str = ""
    sunset_str = ""
    sun = fetch_json("https://api.sunrise-sunset.org/json?lat=YOUR_LAT&lng=YOUR_LON&formatted=0", timeout=5)
    if sun and sun.get("status") == "OK":
        results = sun["results"]
        for key in ["sunrise", "sunset"]:
            try:
                t = datetime.fromisoformat(results[key].replace("Z", "+00:00"))
                local = t.astimezone()
                s = local.strftime("%I:%M").lstrip("0")
                if key == "sunrise":
                    sunrise_str = s
                else:
                    sunset_str = s
            except:
                pass

    def get_icon(short):
        s = short.lower()
        if "thunder" in s or "storm" in s: return "\u26a1", (255, 200, 50)
        if "rain" in s or "shower" in s or "drizzle" in s: return "\u2614", (100, 180, 255)
        if "snow" in s or "flurr" in s or "blizzard" in s: return "\u2744", (200, 220, 255)
        if "fog" in s or "haze" in s or "mist" in s: return "\u2601", (150, 150, 150)
        if "overcast" in s: return "\u2601", (140, 140, 140)
        if "partly" in s and "cloud" in s: return "\u26c5", (200, 200, 200)
        if "cloud" in s: return "\u2601", (170, 170, 170)
        if "wind" in s: return "~", (180, 200, 220)
        if "clear" in s or "sunny" in s or "fair" in s: return "\u2600", (255, 220, 50)
        return "\u2600", (255, 220, 50)

    y = 6
    draw.text((8, y), "FORECAST", fill=ACCENT, font=f_label)

    # Sunrise/sunset on right
    if sunrise_str and sunset_str:
        draw.text((120, y), "\u2600" + sunrise_str, fill=(255, 200, 50), font=f_xs)
        draw.text((175, y), "\u263d" + sunset_str, fill=(150, 150, 200), font=f_xs)
    y += 18

    row_h = 40

    i = 0
    count = 0
    while i < len(periods) and count < 7:
        p = periods[i]
        name = p["name"]
        hi_temp = p["temperature"]
        short = p["shortForecast"]
        is_day = p["isDaytime"]

        lo_temp = None
        if is_day and i + 1 < len(periods):
            lo_temp = periods[i + 1]["temperature"]
            i += 2
        else:
            if not is_day:
                lo_temp = hi_temp
                hi_temp = None
            i += 1

        if "Night" in name or "Tonight" in name:
            day_name = name.replace(" Night", "").replace("Tonight", "Ton")[:3]
        elif name in ("Today", "This Afternoon"):
            day_name = "Tod"
        else:
            day_name = name[:3]

        icon_char, icon_color = get_icon(short)

        # Day name
        draw.text((8, y + 4), day_name, fill=WHITE, font=f_day)

        # Icon
        try:
            draw.text((38, y), icon_char, fill=icon_color, font=f_icon)
        except:
            pass

        # Hi temp
        if hi_temp is not None:
            hi_color = (255, 100, 100) if hi_temp > 95 else ORANGE if hi_temp > 85 else ACCENT if hi_temp < 40 else WHITE
            draw.text((62, y + 3), str(hi_temp) + "\u00b0", fill=hi_color, font=f_hi)

        # Lo temp
        if lo_temp is not None:
            draw.text((100, y + 5), str(lo_temp) + "\u00b0", fill=DIM, font=f_lo)

        # Precip chance
        precip = p.get("probabilityOfPrecipitation", {})
        precip_val = precip.get("value") if precip else None
        if precip_val and precip_val > 0:
            rain_color = ACCENT if precip_val < 50 else ORANGE if precip_val < 80 else (255, 100, 100)
            draw.text((140, y + 5), str(precip_val) + "%", fill=rain_color, font=f_sm)

        # Short forecast summary (truncated)
        short_trunc = short[:22] + ".." if len(short) > 24 else short
        draw.text((8, y + 22), short_trunc, fill=DIM, font=f_xs)

        draw.line([(8, y + row_h - 2), (width - 8, y + row_h - 2)], fill=(30, 33, 43), width=1)
        y += row_h
        count += 1

    return img


def render_network_panel(width=480, height=440):
    """Render network stats + guest WiFi QR code panel."""
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    
    f_label = ImageFont.truetype(FONT_BOLD, 11)
    f_med = ImageFont.truetype(FONT_BOLD, 18)
    f_sm = ImageFont.truetype(FONT, 14)
    f_xs = ImageFont.truetype(FONT, 12)
    
    net = fetch_json("http://127.0.0.1:8092/api/network")
    
    wan_status = net.get('wan_status', '?') if net else '?'
    # wan_ip replaced with dual WAN
    isp = net.get('isp', '?') if net else '?'
    tx = net.get('tx_bps', 0) if net else 0
    rx = net.get('rx_bps', 0) if net else 0
    latency = net.get('latency', 0) if net else 0
    clients = net.get('clients', 0) if net else 0
    wifi_clients = net.get('wifi_clients', 0) if net else 0
    guests = net.get('guests', 0) if net else 0
    gw_cpu = net.get('gw_cpu', '0') if net else '0'
    gw_mem = net.get('gw_mem', '0') if net else '0'
    guest_ssid = net.get('guest_ssid', '') if net else ''
    guest_pass = net.get('guest_pass', '') if net else ''
    guest_sec = net.get('guest_security', 'WPA') if net else 'WPA'
    
    def fmt_speed(bps):
        if bps > 1000000:
            return f"{bps/1000000:.1f} Mbps"
        elif bps > 1000:
            return f"{bps/1000:.0f} Kbps"
        return f"{bps} bps"
    
    y = 8
    
    # NETWORK header
    draw.text((12, y), "NETWORK", fill=ACCENT, font=f_label)
    status_color = GREEN if wan_status == 'ok' else (255, 80, 80)
    draw.text((width - 60, y), wan_status.upper(), fill=status_color, font=f_label)
    y += 18
    
    # Dual WAN status
    wan1_ip = net.get("wan1_ip", "") if net else ""
    wan1_status = net.get("wan1_status", "?") if net else "?"
    wan1_lat = net.get("wan1_latency", 0) if net else 0
    wan2_ip = net.get("wan2_ip", "") if net else ""
    wan2_status = net.get("wan2_status", "?") if net else "?"
    wan2_lat = net.get("wan2_latency", 0) if net else 0
    
    # WAN1 - Fiber (primary)
    w1_color = GREEN if wan1_status == "online" else (255, 80, 80)
    draw.text((12, y), "WAN1 Fiber", fill=WHITE, font=f_sm)
    draw.text((120, y), wan1_status.upper(), fill=w1_color, font=f_xs)
    draw.text((200, y), wan1_ip, fill=DIM, font=f_xs)
    draw.text((380, y), f"{wan1_lat}ms", fill=GRAY, font=f_xs)
    y += 18
    
    # WAN2 - LTE (failover)  
    w2_color = GREEN if wan2_status == "online" else (255, 80, 80)
    draw.text((12, y), "WAN2 LTE", fill=WHITE, font=f_sm)
    draw.text((120, y), wan2_status.upper(), fill=w2_color, font=f_xs)
    draw.text((200, y), wan2_ip, fill=DIM, font=f_xs)
    draw.text((380, y), f"{wan2_lat}ms", fill=GRAY, font=f_xs)
    y += 18
    
    # Speeds
    draw.text((12, y), "Down", fill=DIM, font=f_xs)
    draw.text((55, y), fmt_speed(rx), fill=WHITE, font=f_sm)
    draw.text((240, y), "Up", fill=DIM, font=f_xs)
    draw.text((270, y), fmt_speed(tx), fill=WHITE, font=f_sm)
    y += 20
    
    # Latency
    draw.text((12, y), "Latency", fill=DIM, font=f_xs)
    lat_color = GREEN if latency < 30 else ORANGE if latency < 80 else (255, 80, 80)
    draw.text((70, y), f"{latency}ms", fill=lat_color, font=f_sm)
    y += 22
    
    # Divider
    draw.line([(12, y), (width-12, y)], fill=(30, 33, 43), width=1)
    y += 8
    
    # Clients
    draw.text((12, y), "DEVICES", fill=ACCENT, font=f_label)
    y += 16
    draw.text((12, y), f"{clients}", fill=WHITE, font=f_med)
    draw.text((50, y+4), "total", fill=DIM, font=f_xs)
    draw.text((120, y), f"{wifi_clients}", fill=WHITE, font=f_med)
    draw.text((158, y+4), "WiFi", fill=DIM, font=f_xs)
    draw.text((240, y), f"{guests}", fill=WHITE, font=f_med)
    draw.text((270, y+4), "guests", fill=DIM, font=f_xs)
    y += 24
    
    # Gateway stats
    draw.text((12, y), f"UDM  CPU {gw_cpu}%  MEM {gw_mem}%", fill=DIM, font=f_xs)
    y += 22
    
    # Divider
    draw.line([(12, y), (width-12, y)], fill=(30, 33, 43), width=1)
    y += 8
    
    # Guest WiFi QR
    if guest_ssid and guest_pass:
        draw.text((12, y), "GUEST WIFI", fill=ACCENT, font=f_label)
        y += 18
        draw.text((12, y), guest_ssid, fill=WHITE, font=f_sm)
        y += 18
        draw.text((12, y), f"Pass: {guest_pass}", fill=DIM, font=f_xs)
        y += 20
        
        # Generate QR code
        try:
            import qrcode
            wifi_str = f"WIFI:T:{guest_sec};S:{guest_ssid};P:{guest_pass};;"
            qr = qrcode.QRCode(version=1, box_size=4, border=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(wifi_str)
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="white", back_color="#0d0f14").convert("RGB")
            
            # Center QR code
            qr_size = min(width - 24, height - y - 10)
            qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
            qr_x = (width - qr_size) // 2
            img.paste(qr_img, (qr_x, y))
        except Exception as e:
            draw.text((12, y), f"QR Error: {e}", fill=DIM, font=f_xs)
    
    return img




def render_vehicle_panel(width=400, height=340):
    """Render vehicle telemetry panel (Jeep 4xe + RAV4)."""
    import math
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    f_label = ImageFont.truetype(FONT_BOLD, 11)
    f_title = ImageFont.truetype(FONT_BOLD, 13)
    f_med = ImageFont.truetype(FONT_BOLD, 16)
    f_sm = ImageFont.truetype(FONT, 13)
    f_xs = ImageFont.truetype(FONT, 11)
    f_tiny = ImageFont.truetype(FONT, 10)

    RED = (255, 80, 80)
    PURPLE = (180, 130, 255)

    data = fetch_json("http://127.0.0.1:8092/api/vehicle")
    jeep = data.get("jeep", {}) if data else {}
    rav4 = data.get("rav4", {}) if data else {}

    HOME_LAT, HOME_LON = float(os.getenv("HOME_LAT", "0")), float(os.getenv("HOME_LON", "0"))
    HOME_RADIUS_MI = 0.5

    def is_home(lat, lon):
        if lat is None or lon is None:
            return False
        dlat = (lat - HOME_LAT) * 69.0
        dlon = (lon - HOME_LON) * 69.0 * math.cos(math.radians(HOME_LAT))
        return math.sqrt(dlat**2 + dlon**2) < HOME_RADIUS_MI

    def location_str(vdata):
        lat = vdata.get("lat")
        lon = vdata.get("lon")
        if is_home(lat, lon):
            return "Home"
        loc = vdata.get("location", "")
        if loc:
            return loc[:35]
        return "Unknown"

    y = 6

    # --- JEEP ---
    draw.text((12, y), "JEEP GRAND CHEROKEE 4XE", fill=ACCENT, font=f_label)
    y += 16

    # Charging + EV SOC
    ev_soc = jeep.get("ev_soc")
    charging = jeep.get("ev_charging", False)
    charging_level = jeep.get("ev_charging_level", "")
    fuel_pct = jeep.get("fuel_pct")
    oil_level = jeep.get("oil_level")

    # Line 1: Charging status + EV%
    if charging:
        lvl_str = f" (L{charging_level})" if charging_level else ""
        draw.text((12, y), "\u26a1", fill=GREEN, font=f_sm)
        draw.text((26, y), f"Charging{lvl_str}", fill=GREEN, font=f_sm)
    else:
        plugged = jeep.get("ev_plugged_in", False)
        if plugged:
            draw.text((12, y), "\U0001f50c", fill=GRAY, font=f_sm)
            draw.text((26, y), "Plugged In", fill=GRAY, font=f_sm)
        else:
            draw.text((12, y), "\U0001f50c", fill=DIM, font=f_sm)
            draw.text((26, y), "Not Plugged In", fill=DIM, font=f_sm)

    if ev_soc is not None:
        soc_color = RED if ev_soc < 20 else ORANGE if ev_soc < 50 else GREEN
        draw.text((200, y), f"EV: {ev_soc}%", fill=soc_color, font=f_med)
    y += 18

    # Line 2: Fuel + Oil
    parts = []
    if fuel_pct is not None:
        draw.text((12, y), "\u26fd", fill=GRAY, font=f_sm)
        draw.text((26, y), f"Fuel: {fuel_pct}%", fill=WHITE, font=f_sm)
    if oil_level is not None:
        draw.text((140, y), f"Oil: {oil_level}%", fill=GRAY, font=f_sm)
    y += 16

    # Line 3: Time to full charge
    ttf_l1 = jeep.get("time_to_full_l1")
    ttf_l2 = jeep.get("time_to_full_l2")
    if charging and (ttf_l1 or ttf_l2):
        ttf = ttf_l1 if charging_level in (None, "", "1", 1) else ttf_l2
        lvl = "L1" if charging_level in (None, "", "1", 1) else "L2"
        if ttf and ttf > 0:
            hrs = int(ttf // 60)
            mins = int(ttf % 60)
            draw.text((12, y), "\U0001f50b", fill=GREEN, font=f_sm)
            draw.text((26, y), f"Full in {hrs}h {mins}m ({lvl})", fill=GREEN, font=f_sm)
            y += 16

    # Line 4: Location
    loc = location_str(jeep)
    draw.text((12, y), "\U0001f4cd", fill=GRAY, font=f_sm)
    draw.text((26, y), loc, fill=WHITE, font=f_sm)
    y += 16

    # Line 5: Odometer + voltage
    odo = jeep.get("odometer_mi")
    voltage = jeep.get("battery_voltage")
    odo_str = f"Odo: {odo:,.0f} mi" if odo else "Odo: --"
    volt_str = f"{voltage}V" if voltage else ""
    draw.text((12, y), odo_str, fill=GRAY, font=f_xs)
    if volt_str:
        draw.text((180, y), volt_str, fill=DIM, font=f_xs)
    y += 18

    # Tires section
    draw.text((12, y), "Tires (psi)", fill=DIM, font=f_tiny)
    y += 13

    tire_data = [
        ("FL", jeep.get("tire_fl_psi"), jeep.get("tire_fl_warn")),
        ("FR", jeep.get("tire_fr_psi"), jeep.get("tire_fr_warn")),
        ("RL", jeep.get("tire_rl_psi"), jeep.get("tire_rl_warn")),
        ("RR", jeep.get("tire_rr_psi"), jeep.get("tire_rr_warn")),
    ]

    cx = 12
    for label, psi, warn in tire_data:
        if psi is not None:
            color = RED if warn else WHITE
            txt = f"{label}: {psi}"
            if warn:
                txt += " \u26a0"
            draw.text((cx, y), txt, fill=color, font=f_xs)
        else:
            draw.text((cx, y), f"{label}: --", fill=DIM, font=f_xs)
        cx += 95
        if cx > 200:
            cx = 12
            y += 14

    if len(tire_data) <= 2:
        y += 14
    y += 8

    # Divider
    draw.line([(12, y), (width - 12, y)], fill=(40, 43, 53), width=1)
    y += 8

    # --- RAV4 ---
    draw.text((12, y), "TOYOTA RAV4", fill=ACCENT, font=f_label)
    y += 16

    rav_fuel = rav4.get("fuel_pct")
    if rav_fuel is not None:
        draw.text((12, y), "\u26fd", fill=GRAY, font=f_sm)
        draw.text((26, y), f"Fuel: {rav_fuel}%", fill=WHITE, font=f_sm)
    y += 16

    rav_loc = location_str(rav4)
    draw.text((12, y), "\U0001f4cd", fill=GRAY, font=f_sm)
    draw.text((26, y), rav_loc, fill=WHITE, font=f_sm)
    y += 16

    rav_odo = rav4.get("odometer_mi")
    odo_str = f"Odo: {rav_odo:,.0f} mi" if rav_odo else "Odo: --"
    draw.text((12, y), odo_str, fill=GRAY, font=f_xs)

    return img


def render_panel_strip():
    """Combine all 5 panels into a single 1920x340 image.
    Weather(360) + Forecast(240) + Vehicle(400) + Network(400) + Radar(520) = 1920
    """
    strip = Image.new("RGB", (1920, 340), BG)

    weather = render_current_weather(360, 340)
    forecast = render_forecast(240, 340)
    vehicle = render_vehicle_panel(400, 340)
    network = render_network_panel(400, 340)

    strip.paste(weather, (0, 0))
    strip.paste(forecast, (360, 0))
    strip.paste(vehicle, (600, 0))
    strip.paste(network, (1000, 0))

    # 5th slot: radar image (resized/cropped to 520x340)
    try:
        radar = Image.open("/tmp/radar.png").convert("RGB")
        radar.thumbnail((520, 340), Image.LANCZOS)
        radar_bg = Image.new("RGB", (520, 340), BG)
        rx = (520 - radar.width) // 2
        ry = (340 - radar.height) // 2
        radar_bg.paste(radar, (rx, ry))
        strip.paste(radar_bg, (1400, 0))
    except Exception:
        pass  # radar not available yet

    strip.save("/tmp/panel_strip_tmp.png")
    os.replace("/tmp/panel_strip_tmp.png", "/tmp/panel_strip.png")


def main():
    while True:
        try:
            weather = render_current_weather(360, 340)
            forecast = render_forecast(240, 340)
            weather.save("/tmp/weather_panel_tmp.png")
            os.replace("/tmp/weather_panel_tmp.png", "/tmp/weather_panel.png")
            forecast.save("/tmp/forecast_panel_tmp.png")
            os.replace("/tmp/forecast_panel_tmp.png", "/tmp/forecast_panel.png")

            # Render network panel
            network = render_network_panel(400, 440)
            network.save("/tmp/network_panel_tmp.png")
            os.replace("/tmp/network_panel_tmp.png", "/tmp/network_panel.png")
            # Render combined panel strip
            render_panel_strip()

            print("[" + datetime.now().strftime("%H:%M:%S") + "] Panels rendered", flush=True)

            # Refresh radar
            try:
                import subprocess
                subprocess.run(["curl", "-s", "-o", "/tmp/radar_tmp.png", "--max-time", "15", "http://127.0.0.1:8092/api/radar"], check=True)
                if os.path.getsize("/tmp/radar_tmp.png") > 1000:
                    os.replace("/tmp/radar_tmp.png", "/tmp/radar.png")
                    print("Radar refreshed", flush=True)
            except Exception as re:
                print("Radar refresh error: " + str(re), flush=True)
        except Exception as e:
            print("Error: " + str(e), flush=True)
        time.sleep(30)

if __name__ == "__main__":
    main()
