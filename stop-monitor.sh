#!/bin/bash
if [ -f /tmp/home-monitor.pid ]; then
    kill $(cat /tmp/home-monitor.pid) 2>/dev/null
    rm /tmp/home-monitor.pid
    echo "Home Monitor stopped"
else
    echo "No PID file found"
    pkill -f 'python app.py' 2>/dev/null
fi
