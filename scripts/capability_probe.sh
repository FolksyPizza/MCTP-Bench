#!/usr/bin/env bash
# Capability gate: quickly probe whether a model is strong enough to be worth benchmarking.
#
# A model that fails most tasks makes every condition look the same (nothing performs, so nothing
# distinguishes transcript from mctp). We therefore require a minimum pass rate on a small, neutral
# probe (HumanEval + GSM8K, transcript condition) BEFORE committing a model to the full sweep.
# Pick recent OSS models that clear the bar empirically here — not ones merely claimed to be good.
#
#   bash scripts/capability_probe.sh <model> <url> [N] [THRESHOLD]
#
# N tasks per suite (default 20), THRESHOLD pass fraction to "pass the gate" (default 0.40).
set -euo pipefail

MODEL="${1:?usage: capability_probe.sh <model> <url> [N] [threshold]}"
URL="${2:-http://localhost:8000/v1}"
N="${3:-20}"
THRESH="${4:-0.40}"
MAXTOK="${MAXTOK:-1024}"   # raise (e.g. 4096) for reasoning models that spend budget on thinking
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
OUT="/tmp/capprobe_$(echo "$MODEL" | tr '/:' '__')"
rm -rf "$OUT"

echo "capability probe: model=$MODEL  N=$N/suite  threshold=$THRESH"
for suite in humaneval gsm8k; do
  .venv/bin/python run_benchmark.py --suite "$suite" --models "$MODEL" --url "$URL" \
    --conditions transcript --trials 1 --limit "$N" --max-tokens "$MAXTOK" --concurrency 4 \
    --telemetry-port 0 --results "$OUT" >/dev/null 2>&1 || true
done

.venv/bin/python - "$OUT" "$THRESH" "$MODEL" <<'PY'
import sys, glob, json
out, thresh, model = sys.argv[1], float(sys.argv[2]), sys.argv[3]
by = {}
for p in glob.glob(f"{out}/runs/*/*/*.jsonl"):
    for l in open(p):
        r = json.loads(l)
        by.setdefault(r["suite"], []).append(r["objective_pass"])
total_ok = total_n = 0
for suite, ps in sorted(by.items()):
    ok = sum(1 for p in ps if p); n = sum(1 for p in ps if p is not None)
    total_ok += ok; total_n += n
    print(f"  {suite:10} {ok}/{n} = {ok/max(1,n):.0%}")
rate = total_ok / max(1, total_n)
verdict = "PASSES gate" if rate >= thresh else "FAILS gate"
print(f"  overall    {total_ok}/{total_n} = {rate:.0%}  -> {model} {verdict} (threshold {thresh:.0%})")
sys.exit(0 if rate >= thresh else 1)
PY
