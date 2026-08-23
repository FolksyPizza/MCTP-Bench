#!/usr/bin/env bash
# Fetch external benchmark datasets into data/. Run on the host after setup_host.sh, from inside
# the venv (needs `datasets` for the prepare step).
#
# HumanEval is a direct download; the rest are fetched and converted by prepare_datasets.py.
# SWE-bench also gets a per-instance `files` snapshot (swebench_files) via repo checkout, which
# needs git + network + disk; skip it with FETCH_SWEBENCH_FILES=0 for a metadata-only run.
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

echo "Preparing MBPP, GSM8K, LongBench, RepoBench, SWE-bench metadata (via datasets) ..."
python "$HERE/scripts/prepare_datasets.py" --suite mbpp gsm8k longbench repobench swebench

if [ "${FETCH_SWEBENCH_FILES:-1}" = "1" ]; then
  echo "Materializing SWE-bench file snapshots (repo checkouts; set FETCH_SWEBENCH_FILES=0 to skip) ..."
  python "$HERE/scripts/prepare_datasets.py" --suite swebench_files
fi

echo "Done. Adapters use data/<suite>.jsonl when present, else the bundled sample."
