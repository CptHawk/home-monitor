#!/bin/bash
# Build and optionally deploy the Roku channel
# Usage: ./build.sh [roku_ip] [password]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="/tmp/roku-home-monitor.zip"

cd "$SCRIPT_DIR"

# Create placeholder images if they don't exist
mkdir -p images
if [ ! -f images/icon_focus_hd.png ]; then
    echo "Creating placeholder icons..."
    python3 -c "
import struct, zlib
def make_png(w, h, r, g, b, path):
    def chunk(t, d):
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    raw = b''
    for y in range(h):
        raw += b'\x00' + bytes([r, g, b]) * w
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
make_png(336, 210, 26, 29, 39, 'images/icon_focus_hd.png')
make_png(108, 69, 26, 29, 39, 'images/icon_side_hd.png')
make_png(1920, 1080, 10, 12, 18, 'images/splash_hd.jpg')
"
fi

# Package
zip -r "$OUTPUT" manifest source/ components/ images/
echo "Built: $OUTPUT"

# Deploy if IP provided
if [ -n "$1" ]; then
    ROKU_IP="$1"
    ROKU_PASS="${2:-rokudev}"
    echo "Deploying to $ROKU_IP..."
    curl -s --digest -u "rokudev:$ROKU_PASS" \
        -F "mysubmit=Install" \
        -F "archive=@$OUTPUT" \
        "http://$ROKU_IP/plugin_install" | grep -oP '(?<=<font color="red">).*?(?=</font>)'
fi
