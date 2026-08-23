#!/usr/bin/env bash
# Prepare the GPU host to run MCTP-Bench co-located with the model server.
#
# Unprivileged: creates a Python venv and installs the harness dependencies and vLLM. Does NOT
# install system packages, load a model, or start any server. Run it once on the host, then
# start vLLM separately (see docs/BENCHMARK.md) before invoking run_benchmark.py.
#
#   bash scripts/setup_host.sh [WORKDIR]
#
# WORKDIR defaults to ~/mctp. It clones MCTP and MCTP-Bench side by side (MCTP_HOME resolves to
# the sibling ../MCTP) and builds .venv in MCTP-Bench.
set -euo pipefail

WORKDIR="${1:-$HOME/mctp}"
mkdir -p "$WORKDIR"
cd "$WORKDIR"

clone_or_pull() {  # repo_url dir
  if [ -d "$2/.git" ]; then git -C "$2" pull --ff-only; else git clone "$1" "$2"; fi
}
clone_or_pull https://github.com/FolksyPizza/MCTP.git MCTP
clone_or_pull https://github.com/FolksyPizza/MCTP-Bench.git MCTP-Bench

cd MCTP-Bench
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
# Harness dependencies: tiktoken (reference tokenizers) and datasets (to fetch/convert the
# benchmark suites). transformers is optional (native HF tokenizers) and pulled in with vLLM.
python -m pip install tiktoken datasets
# Inference server. vLLM brings torch, transformers, and the OpenAI-compatible server.
python -m pip install vllm

echo
echo "Setup complete."
echo "  harness:   $WORKDIR/MCTP-Bench  (.venv ready, MCTP_HOME -> ../MCTP)"
echo "  next:      fetch datasets (scripts/fetch_datasets.sh), then start vLLM, then run_benchmark.py"
echo "  smoke:     .venv/bin/python run_benchmark.py --suite humaneval --dry-run"
