#!/bin/bash
# Updates /tmp/grid_info_overlay.txt every 30s with weather + thermostat data
# ffmpeg reads this file via textfile= with reload=1

while true; do
    # Fetch weather
    WX=$(curl -s --max-time 5 "http://127.0.0.1:8092/api/weather" 2>/dev/null)
    if [ -n "$WX" ] && echo "$WX" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        OUT_TEMP=$(echo "$WX" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('temp_f','?'))" 2>/dev/null)
        OUT_HUM=$(echo "$WX" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('humidity','?'))" 2>/dev/null)
        OUT_WIND=$(echo "$WX" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('windSpeed','0'))" 2>/dev/null)
        OUT_RAIN=$(echo "$WX" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('precipTotal','0.0'))" 2>/dev/null)
        OUT_UV=$(echo "$WX" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('uv','0'))" 2>/dev/null)
        OUT_PRESS=$(echo "$WX" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('pressure','?'))" 2>/dev/null)
    fi

    # Fetch thermostat
    THERMO=$(curl -s --max-time 5 "http://127.0.0.1:8092/api/thermostat" 2>/dev/null)
    if [ -n "$THERMO" ] && echo "$THERMO" | python3 -c "import sys,json; json.load(sys.stdin)" 2>/dev/null; then
        IN_TEMP=$(echo "$THERMO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('temperature_f','?'))" 2>/dev/null)
        IN_HUM=$(echo "$THERMO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('humidity','?'))" 2>/dev/null)
        IN_MODE=$(echo "$THERMO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','?').upper())" 2>/dev/null)
        IN_HVAC=$(echo "$THERMO" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('hvac_status','?').upper())" 2>/dev/null)
        IN_SET=$(echo "$THERMO" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d.get('cool_setpoint_c') or d.get('heat_setpoint_c'); print(round(c*9/5+32) if c else '?')" 2>/dev/null)
    fi

    # Write overlay text (ffmpeg reloads this)
    cat > /tmp/grid_info_overlay.txt << EOF
OUTSIDE  ${OUT_TEMP:-?}F  ${OUT_HUM:-?}%%
Wind ${OUT_WIND:-0}mph  Rain ${OUT_RAIN:-0}in  UV ${OUT_UV:-0}
${OUT_PRESS:-?} inHg

INSIDE  ${IN_TEMP:-?}F  ${IN_HUM:-?}%%
${IN_MODE:-?}  HVAC ${IN_HVAC:-?}  Set ${IN_SET:-?}F

Doors: Awaiting sensors
EOF

    sleep 30
done
