#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PORT="${HUB_PORT:-8788}"
PIDFILE="hub.pid"
LOGFILE="hub.log"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "hub already running (pid $(cat "$PIDFILE")) on port $PORT"
  exit 0
fi

setsid nohup python3 hunt_hub.py --port "$PORT" > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"
echo "hub started (pid $(cat "$PIDFILE")) on port $PORT"
