#!/bin/zsh
set -e
cd "$(dirname "$0")"
python3 app.py &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT INT TERM
sleep 1
open "http://127.0.0.1:8765"
wait $PID
