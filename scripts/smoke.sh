#!/usr/bin/env bash
# A fast first run to confirm the end-to-end path (streaming capture, native tokens, objective
# scoring, resume, telemetry) before committing to a full wave.
#
#   bash scripts/smoke.sh [MODEL] [URL] [MODE]
#
# MODE=low (default): the low-context suites, 10 tasks each, transcript+mctp — quick and cheap.
# MODE=all:           ONE task from every suite/category (all conditions) — broadest coverage,
#                     exercises every adapter, condition, the extractor, and the swarm pipeline.
#
# Watch it live in another terminal:  python monitor.py
set -euo pipefail

MODEL="${1:-qwen2.5-coder:14b}"
URL="${2:-http://localhost:8000/v1}"
MODE="${3:-low}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

echo "smoke run: model=$MODEL  url=$URL  mode=$MODE"

if [ "$MODE" = "all" ]; then
  # One scenario from each category, all conditions the suite defines.
  SUITES="humaneval mbpp gsm8k multifile inhouse repobench longbench swebench swarm"
  for suite in $SUITES; do
    python run_benchmark.py --suite "$suite" --models "$MODEL" --url "$URL" \
      --trials 1 --limit 1 --max-tokens 4096 --progress-every 1 --resume
  done
else
  for suite in humaneval mbpp gsm8k; do
    python run_benchmark.py --suite "$suite" --models "$MODEL" --url "$URL" \
      --conditions transcript,mctp --trials 1 --limit 10 --max-tokens 2048 \
      --progress-every 5 --resume
  done
fi

echo
echo "Objective scoring + pricing (run the judge pass separately):"
python analyze.py
echo "Done. Results under results/ ; per-suite checkpoints under results/progress/."
