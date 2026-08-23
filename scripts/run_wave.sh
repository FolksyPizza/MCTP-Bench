#!/usr/bin/env bash
# Run a wave: for each model, start vLLM, run the given suites, then stop vLLM (unload the model)
# before the next model — so only the model in use holds the GPU.
#
#   bash scripts/run_wave.sh "modelA modelB" "humaneval mbpp gsm8k inhouse" [PORT] [TP]
#
# Env: TRIALS (default 3), MAX_TOKENS (default 4096), WINDOW (e.g. 23:00-06:00), EXTRA_ARGS.
# Resumable: re-running continues where it stopped (each run_benchmark call uses --resume).
set -euo pipefail

MODELS="${1:?usage: run_wave.sh \"model...\" \"suite...\" [port] [tp]}"
SUITES="${2:?suites}"
PORT="${3:-8000}"
TP="${4:-2}"
URL="http://localhost:${PORT}/v1"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

WINDOW_ARG=(); [ -n "${WINDOW:-}" ] && WINDOW_ARG=(--window "$WINDOW")

for MODEL in $MODELS; do
  bash scripts/serve_vllm.sh "$MODEL" "$PORT" "$TP"
  for SUITE in $SUITES; do
    # shellcheck disable=SC2086
    python run_benchmark.py --suite "$SUITE" --models "$MODEL" --url "$URL" \
      --trials "${TRIALS:-3}" --max-tokens "${MAX_TOKENS:-4096}" --resume \
      "${WINDOW_ARG[@]}" ${EXTRA_ARGS:-}
  done
  bash scripts/stop_vllm.sh "$PORT"   # unload before the next model frees the GPU
done

python analyze.py
echo "wave complete."
