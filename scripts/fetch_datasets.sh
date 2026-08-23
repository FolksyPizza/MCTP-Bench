#!/usr/bin/env bash
# Fetch external benchmark datasets into data/. Run on the host after setup_host.sh, from inside
# the venv (needs `datasets` for the prepare step).
#
# HumanEval is a direct download; MBPP, GSM8K, LongBench, and SWE-bench metadata are fetched and
# converted by scripts/prepare_datasets.py. RepoBench and the SWE-bench `files` snapshots need a
# dataset-specific / checkout step (see prepare_datasets.py) and are not fetched here yet.
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

echo "Preparing MBPP, GSM8K, LongBench, SWE-bench metadata (via the datasets library) ..."
python "$HERE/scripts/prepare_datasets.py" --suite mbpp gsm8k longbench swebench

echo "Done. Adapters use data/<suite>.jsonl when present, else the bundled sample."
