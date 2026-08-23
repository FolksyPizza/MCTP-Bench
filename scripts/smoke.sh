#!/usr/bin/env bash
# A fast first run: one small model, the low-context suites, a few tasks each, two conditions.
# Confirms the end-to-end path (streaming capture, native tokens, objective scoring, resume,
# telemetry) in a few minutes before committing to a full wave.
#
#   bash scripts/smoke.sh [MODEL] [URL]
#
# Watch it live in another terminal:  python monitor.py
set -euo pipefail

MODEL="${1:-qwen2.5-coder:14b}"
URL="${2:-http://localhost:8000/v1}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

echo "smoke run: model=$MODEL  url=$URL"
for suite in humaneval mbpp gsm8k; do
  python run_benchmark.py --suite "$suite" --models "$MODEL" --url "$URL" \
    --conditions transcript,mctp --trials 1 --limit 10 --max-tokens 2048 \
    --progress-every 5 --resume
done

echo
echo "Scoring + pricing (objective only; run the judge pass separately):"
python analyze.py
echo "Done. Results under results/ ; per-suite checkpoints under results/progress/."
