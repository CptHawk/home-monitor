#!/bin/bash
# Fetches weather and thermostat data every 30 seconds
# Writes variables to /tmp/overlay_info.txt for ffmpeg drawtext overlays

API_HOST="${1:-localhost:8092}"

while true; do
  WEATHER=$(curl -s "http://${API_HOST}/api/weather" 2>/dev/null)
  WX_TEMP=$(echo $WEATHER | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("temp_f","--"))' 2>/dev/null || echo '--')
  WX_HUMID=$(echo $WEATHER | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("humidity","--"))' 2>/dev/null || echo '--')
  WX_WIND=$(echo $WEATHER | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("windSpeed",0))' 2>/dev/null || echo '0')
  WX_GUST=$(echo $WEATHER | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("windGust",0))' 2>/dev/null || echo '0')
  WX_RAIN=$(echo $WEATHER | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("precipTotal",0))' 2>/dev/null || echo '0')
  WX_PRESS=$(echo $WEATHER | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("pressure","--"))' 2>/dev/null || echo '--')
  WX_UV=$(echo $WEATHER | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("uv","--"))' 2>/dev/null || echo '--')

  THERMO=$(curl -s "http://${API_HOST}/api/thermostat" 2>/dev/null)
  TH_TEMP=$(echo $THERMO | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("temperature_f","--"))' 2>/dev/null || echo '--')
  TH_HUMID=$(echo $THERMO | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("humidity","--"))' 2>/dev/null || echo '--')
  TH_MODE=$(echo $THERMO | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("mode","--"))' 2>/dev/null || echo '--')
  TH_HVAC=$(echo $THERMO | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("hvac_status","--"))' 2>/dev/null || echo '--')
  TH_SET=$(echo $THERMO | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d.get("cool_setpoint_c") or d.get("heat_setpoint_c"); print(round(c*9/5+32) if c else "--")' 2>/dev/null || echo '--')

  cat > /tmp/overlay_info.txt << EOF
WX_TEMP=${WX_TEMP}
WX_HUMID=${WX_HUMID}
WX_WIND=${WX_WIND}
WX_GUST=${WX_GUST}
WX_RAIN=${WX_RAIN}
WX_PRESS=${WX_PRESS}
WX_UV=${WX_UV}
TH_TEMP=${TH_TEMP}
TH_HUMID=${TH_HUMID}
TH_MODE=${TH_MODE}
TH_HVAC=${TH_HVAC}
TH_SET=${TH_SET}
EOF

  sleep 30
done
