#!/usr/bin/env bash
# Fetch external benchmark datasets into data/. Run on the host after setup_host.sh.
#
# Currently fetches HumanEval (164 problems, a single gzipped JSONL). Larger suites
# (SWE-bench environments, long-context sets) are added here as their adapters land.
#
#   bash scripts/fetch_datasets.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$HERE/data"
mkdir -p "$DATA"

HUMANEVAL_URL="https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz"
if [ ! -f "$DATA/HumanEval.jsonl" ]; then
  echo "Fetching HumanEval -> $DATA/HumanEval.jsonl"
  curl -fsSL "$HUMANEVAL_URL" -o "$DATA/HumanEval.jsonl.gz"
  gunzip -f "$DATA/HumanEval.jsonl.gz"
else
  echo "HumanEval already present."
fi

echo "Done. The humaneval adapter uses data/HumanEval.jsonl when present (else the bundled sample)."
