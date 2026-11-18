#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PIDFILE="hub.pid"

if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    for i in $(seq 1 20); do
      kill -0 "$PID" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi
pkill -f "hunt_hub.py" 2>/dev/null || true
echo "hub stopped"
