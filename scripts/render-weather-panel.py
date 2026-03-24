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

def render_current_weather(width=480, height=340):
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
    draw.text((12, y), "Awaiting CR2 batteries", fill=DIM, font=f_sm)

    # Clock bottom right
    now = datetime.now()
    draw.text((width-145, height-42), now.strftime("%I:%M %p"), fill=WHITE, font=f_med)
    draw.text((width-145, height-20), now.strftime("%A %b %d"), fill=DIM, font=f_xs)

    return img


def render_forecast(width=480, height=340):
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)
    f_label = ImageFont.truetype(FONT_BOLD, 11)
    f_day = ImageFont.truetype(FONT_BOLD, 14)
    f_temp = ImageFont.truetype(FONT_BOLD, 18)
    f_desc = ImageFont.truetype(FONT, 11)
    f_sm = ImageFont.truetype(FONT, 12)

    data = fetch_json("https://api.weather.gov/gridpoints/YOUR_NWS_OFFICE/YOUR_GRID_X,YOUR_GRID_Y/forecast", timeout=10)
    if not data or "properties" not in data:
        draw.text((12, 12), "7-DAY FORECAST", fill=ACCENT, font=f_label)
        draw.text((12, 30), "Loading...", fill=DIM, font=f_sm)
        return img

    periods = data["properties"]["periods"][:14]
    draw.text((12, 6), "7-DAY FORECAST", fill=ACCENT, font=f_label)

    y = 24
    row_h = 44
    i = 0
    count = 0

    while i < len(periods) and count < 7:
        p = periods[i]
        name = p["name"]
        temp = p["temperature"]
        short = p["shortForecast"]
        is_day = p["isDaytime"]

        night_temp = ""
        if is_day and i+1 < len(periods):
            night_temp = str(periods[i+1]["temperature"]) + chr(176)
            i += 2
        else:
            i += 1

        # Short day name
        if "Night" in name or "Tonight" in name:
            day_name = name.replace(" Night", "").replace("Tonight", "Ton")[:3]
        elif name in ("Today", "This Afternoon"):
            day_name = "Tod"
        else:
            day_name = name[:3]

        draw.text((12, y+2), day_name, fill=WHITE, font=f_day)

        # Temp with color
        temp_color = ORANGE if temp > 85 else (255, 100, 100) if temp > 95 else ACCENT if temp < 40 else WHITE
        draw.text((65, y), str(temp) + chr(176), fill=temp_color, font=f_temp)

        if night_temp:
            draw.text((115, y+4), "/" + night_temp, fill=DIM, font=f_sm)

        # Forecast text
        desc = short[:30] + ".." if len(short) > 30 else short
        draw.text((175, y+4), desc, fill=GRAY, font=f_desc)

        # Precip chance
        precip = p.get("probabilityOfPrecipitation", {})
        precip_val = precip.get("value") if precip else None
        if precip_val and precip_val > 0:
            rain_color = ACCENT if precip_val < 50 else ORANGE if precip_val < 80 else (255, 100, 100)
            draw.text((width-50, y+4), str(precip_val) + "%", fill=rain_color, font=f_sm)

        draw.line([(12, y+row_h-4), (width-12, y+row_h-4)], fill=(30, 33, 43), width=1)
        y += row_h
        count += 1

    return img


def main():
    while True:
        try:
            weather = render_current_weather(480, 340)
            forecast = render_forecast(480, 340)
            weather.save("/tmp/weather_panel_tmp.png")
            os.replace("/tmp/weather_panel_tmp.png", "/tmp/weather_panel.png")
            forecast.save("/tmp/forecast_panel_tmp.png")
            os.replace("/tmp/forecast_panel_tmp.png", "/tmp/forecast_panel.png")
            print("[" + datetime.now().strftime("%H:%M:%S") + "] Panels rendered", flush=True)
        except Exception as e:
            print("Error: " + str(e), flush=True)
        time.sleep(30)

if __name__ == "__main__":
    main()
