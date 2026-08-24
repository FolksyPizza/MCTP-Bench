#!/usr/bin/env bash
# Set up vLLM for a WSL2 GPU host, where the current vLLM V1 engine fails
# (`RuntimeError: UVA is not available` — WSL2 does not provide Unified Virtual Addressing).
#
# Solution: a dedicated venv with vLLM 0.9.2, which still supports the V0 engine
# (VLLM_USE_V1=0, no UVA buffers). Two pins/patches are needed:
#   - transformers==4.52.4 (0.9.2 is incompatible with transformers 5.x)
#   - a conditional guard around vLLM's unconditional `aimv2` config registration
#     (a known 0.9.2 bug that clashes with transformers>=4.52).
#
# The harness talks to the server over HTTP, so this venv is separate from the harness venv.
# Start the server with VLLM_USE_V1=0 (see scripts/serve_vllm.sh or start_vllm.sh).
#
#   bash scripts/setup_vllm_wsl.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

python3 -m venv .venv-vllm
.venv-vllm/bin/pip install --upgrade pip
.venv-vllm/bin/pip install "vllm==0.9.2" "transformers==4.52.4"

# Guard the aimv2 registration (vLLM 0.9.2 registers it unconditionally; transformers>=4.52
# already provides it).
OVIS=$(.venv-vllm/bin/python -c "import vllm.transformers_utils.configs.ovis as m; print(m.__file__)")
.venv-vllm/bin/python - "$OVIS" <<'PY'
import sys
f = sys.argv[1]
s = open(f).read()
old = 'AutoConfig.register("aimv2", AIMv2Config)'
new = ('try:\n    AutoConfig.register("aimv2", AIMv2Config)\n'
       'except ValueError:\n    pass  # already registered by transformers>=4.52')
if old in s and "except ValueError" not in s:
    open(f, "w").write(s.replace(old, new)); print("patched aimv2 registration")
else:
    print("aimv2 already patched or pattern missing")
PY

echo
echo "vLLM (WSL) ready in .venv-vllm. Start it with, e.g.:"
echo "  VLLM_USE_V1=0 .venv-vllm/bin/python -m vllm.entrypoints.openai.api_server \\"
echo "    --model <hf-model> --port 8000 --max-model-len 8192 --gpu-memory-utilization 0.90"
