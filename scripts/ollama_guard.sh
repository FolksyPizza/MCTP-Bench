#!/usr/bin/env bash
# Keep the GPU free for a vLLM sweep by periodically unloading any loaded Ollama models.
#
# Use on a shared host where OLLAMA_KEEP_ALIVE can't be changed (no sudo, root owns the service).
# Ollama loads a model only when a request arrives, so with nothing querying it this is a no-op
# after the first stop; it exists to catch a model another user loads mid-sweep. Run it alongside
# the sweep (e.g. in a second tmux pane) and Ctrl-C when done.
#
#   bash scripts/ollama_guard.sh [INTERVAL_SECONDS]   # default 30
set -euo pipefail

INTERVAL="${1:-30}"
echo "ollama-guard: unloading any loaded models every ${INTERVAL}s (Ctrl-C to stop)"
while true; do
  names=$(ollama ps 2>/dev/null | tail -n +2 | awk '{print $1}')
  for n in $names; do ollama stop "$n" >/dev/null 2>&1 || true; done
  [ -n "$names" ] && echo "$(date +%H:%M:%S) unloaded: $(echo $names | tr '\n' ' ')"
  sleep "$INTERVAL"
done
