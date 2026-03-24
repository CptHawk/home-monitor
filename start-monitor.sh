#!/bin/bash
cd "$(dirname "$0")"
source ./venv/bin/activate 2>/dev/null || source ../home-monitor-venv/bin/activate 2>/dev/null
nohup python app.py > /tmp/home-monitor.log 2>&1 &
echo $! > /tmp/home-monitor.pid
echo "Home Monitor started on port ${SERVER_PORT:-8092} (PID: $(cat /tmp/home-monitor.pid))"
