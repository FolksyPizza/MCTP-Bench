#!/usr/bin/env bash
# Stop the vLLM server on a port, freeing the GPU (unload the model when it is not in use).
#
#   bash scripts/stop_vllm.sh [PORT]
set -euo pipefail

PORT="${1:-8000}"
PIDFILE="/tmp/vllm_${PORT}.pid"

if [ -f "$PIDFILE" ]; then
  PID="$(cat "$PIDFILE")"
  kill "$PID" 2>/dev/null || true
  for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
  kill -9 "$PID" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "stopped vLLM on :$PORT (pid $PID); GPU freed"
else
  pkill -f "vllm.entrypoints.openai.api_server.*--port ${PORT}" 2>/dev/null || true
  echo "stopped vLLM on :$PORT (by pattern)"
fi
