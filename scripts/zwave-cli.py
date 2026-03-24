#!/usr/bin/env python3
"""Z-Wave JS UI CLI - Socket.IO websocket API with ack callbacks"""
import sys, json, os, threading
import websocket

# Configure via argument or environment variable
DEFAULT_HOST = os.environ.get('ZWAVE_HOST', 'localhost:8091')
ACK_ID = 1  # Socket.IO ack packet ID

def call_api(url, api_name, args=None):
    if args is None:
        args = []

    result = {}
    done = threading.Event()

    def on_message(ws, msg):
        if msg == '2':
            ws.send('3')
            return
        if msg.startswith('0'):
            ws.send('40')
        elif msg.startswith('40'):
            # Connected - send API call with ack ID
            # Socket.IO ack format: 42<id>[event, data]
            payload = json.dumps(['ZWAVE_API', {'api': api_name, 'args': args}])
            ws.send(f'42{ACK_ID}{payload}')
        elif msg.startswith('43'):
            # Ack response: 43<id>[data]
            # Strip '43' and the ack ID
            ack_data = msg[2:]
            # Remove leading digits (ack ID)
            i = 0
            while i < len(ack_data) and ack_data[i].isdigit():
                i += 1
            data = json.loads(ack_data[i:])
            result['data'] = data[0] if isinstance(data, list) and len(data) > 0 else data
            done.set()

    def on_error(ws, e):
        print(f'Error: {e}', file=sys.stderr)
        done.set()

    ws = websocket.WebSocketApp(url,
        on_message=on_message,
        on_error=on_error)

    t = threading.Thread(target=ws.run_forever)
    t.daemon = True
    t.start()

    done.wait(timeout=10)

    if 'data' in result:
        r = result['data']
        if r.get('success'):
            out = r.get('result')
            if out is not None:
                print(json.dumps(out, indent=2, default=str))
            else:
                print('OK')
        else:
            print(f"Error: {r.get('message', 'Unknown error')}", file=sys.stderr)
            sys.exit(1)
    else:
        print('Timeout waiting for response', file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Z-Wave JS UI CLI')
        print(f'Usage: zwave-cli.py [host:port] <command> [args...]')
        print(f'  Default host: {DEFAULT_HOST} (override with ZWAVE_HOST env var)')
        print()
        print('Commands:')
        print('  getInfo              Controller info')
        print('  getNodes             List all nodes')
        print('  startInclusion       Start pairing mode')
        print('  stopInclusion        Stop pairing mode')
        print('  startExclusion       Start exclusion mode')
        print('  stopExclusion        Stop exclusion mode')
        print('  pingNode <id>        Ping a node')
        print('  removeFailedNode <id>  Remove failed node')
        print('  refreshInfo <id>     Re-interview a node')
        sys.exit(0)

    # Check if first arg looks like a host:port
    host = DEFAULT_HOST
    cmd_start = 1
    if ':' in sys.argv[1] and not sys.argv[1].startswith('-'):
        # Could be host:port - check if it has digits after colon
        parts = sys.argv[1].rsplit(':', 1)
        if parts[1].isdigit():
            host = sys.argv[1]
            cmd_start = 2

    if cmd_start >= len(sys.argv):
        print('Error: no command specified', file=sys.stderr)
        sys.exit(1)

    url = f'ws://{host}/socket.io/?EIO=4&transport=websocket'
    api = sys.argv[cmd_start]
    args = []
    for a in sys.argv[cmd_start + 1:]:
        try:
            args.append(json.loads(a))
        except json.JSONDecodeError:
            args.append(a)

    call_api(url, api, args)
