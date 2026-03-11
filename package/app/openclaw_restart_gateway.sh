#!/bin/sh

OPENCLAW_CMD="$1"
PORT="18789"

if [ -z "$OPENCLAW_CMD" ]; then
  exit 1
fi

"$OPENCLAW_CMD" gateway stop >/dev/null 2>&1 || true
sleep 2

if command -v lsof >/dev/null 2>&1; then
  PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    kill -9 $PIDS >/dev/null 2>&1 || true
    sleep 2
  fi
fi

nohup "$OPENCLAW_CMD" gateway start >/dev/null 2>&1 &
