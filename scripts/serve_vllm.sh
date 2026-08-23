#!/usr/bin/env bash
# Start a vLLM OpenAI-compatible server for one model and wait until it is healthy.
#
#   bash scripts/serve_vllm.sh <hf-model> [PORT] [TENSOR_PARALLEL]
#
# Env: MAX_MODEL_LEN (default 8192), EXTRA_VLLM_ARGS (appended verbatim).
# Writes the PID to /tmp/vllm_<port>.pid and logs to /tmp/vllm_<port>.log so stop_vllm.sh can
# shut it down (freeing the GPU) when the model is not in use.
set -euo pipefail

MODEL="${1:?usage: serve_vllm.sh <hf-model> [port] [tp]}"
PORT="${2:-8000}"
TP="${3:-2}"
LOG="/tmp/vllm_${PORT}.log"

echo "starting vLLM: model=$MODEL port=$PORT tp=$TP (log $LOG)"
# shellcheck disable=SC2086
python -m vllm.entrypoints.openai.api_server --model "$MODEL" --port "$PORT" \
  --tensor-parallel-size "$TP" --max-model-len "${MAX_MODEL_LEN:-8192}" \
  ${EXTRA_VLLM_ARGS:-} >"$LOG" 2>&1 &
echo $! > "/tmp/vllm_${PORT}.pid"

for _ in $(seq 1 120); do
  if curl -fsS "http://localhost:${PORT}/health" >/dev/null 2>&1; then
    echo "vLLM healthy on :$PORT"
    exit 0
  fi
  sleep 5
done
echo "vLLM did not become healthy within ~10 min; see $LOG" >&2
exit 1
