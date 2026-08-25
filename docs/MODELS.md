# Models under evaluation

MCTP-Bench measures a context-transfer protocol, so the receiver models must actually be able to
perform the tasks — a model that fails most tasks makes every condition look identical and hides
any real difference between transcript, summary, RAG, and MCTP. Every model therefore passes a
**capability gate** before it is admitted to the full suite, and this page records what we run on,
what passed, and what proved unsuitable.

## Capability gate

`scripts/capability_probe.sh <model> <url>` probes a model on a neutral sample (HumanEval + GSM8K,
transcript condition) and reports a pass rate with a go/no-go against a threshold (default 40%).
Only models that clear the gate empirically — because they perform here, not because they are
reputed to — are used for results. Reasoning models are given a larger generation budget so they
finish thinking before answering.

## Serving

vLLM is the standard runner for all evaluation and results (an OpenAI-compatible server; the
harness talks to it over HTTP). On this GPU host (WSL2, 2x RTX 3090) vLLM 0.9.2 is used with the
V0 engine (`VLLM_USE_V1=0`) and the setup in `scripts/setup_vllm_wsl.sh`; models 27B and larger are
served AWQ-quantized, 1-2 loaded at a time, at a 32K context window. Earlier smoke/gating runs used
Ollama for convenience; those capability numbers are being re-confirmed on vLLM, which is the
system of record going forward.

## Model tiers

- **Telemetry / development tier (~14B):** fast, large-scale plumbing and throughput runs. Not used
  for final results.
- **Results tier (20-35B, capability-gated):** the models final results are reported on. The suite
  spans at least four model families for cross-model evidence, and includes a reasoning model.

## Status

Legend: ✅ passes the gate · ⚠️ passes but weak on some tasks · ❌ unsuitable.

| Model | Family | Size | Served | Gate (HumanEval / GSM8K) | Status |
|-------|--------|------|--------|--------------------------|--------|
| **Qwen3-32B-AWQ** | Qwen3 | 32B | **vLLM** | **97% (14/15, 15/15)** | ✅ **results tier (vLLM-confirmed)** |
| Gemma 3 27B | Gemma | 27B | Ollama (vLLM pending) | 92% (12/12, 10/12) | ✅ results candidate — 2nd family |
| Qwen3 35B (qwen3:35b build) | Qwen3 | 35B | Ollama | 75% (6/12, 12/12) | ⚠️ passes; weaker on code than the 27B |
| gpt-oss 20B | GPT-OSS | 20B | Ollama | errored (HTTP 500) | ❌ unsuitable on this build |
| Qwen2.5-14B-Instruct | Qwen2.5 | 14B | vLLM | HumanEval 4/5 (spot) | ✅ telemetry tier |
| Qwen2.5-Coder-7B | Qwen2.5 | 7B | vLLM | too weak (near-0 on hard tasks) | ❌ below results floor |

Notes:
- Bigger is not automatically better: the 35B scored lower on code (6/12) than the 27B (12/12) —
  the reason capability is gated empirically rather than assumed.
- Family breadth: two families (Qwen3, Gemma) are confirmed; a strong code model
  (e.g. Qwen2.5-Coder-32B) and a further family (e.g. Mistral-Small-24B, Phi-4) are being gated on
  vLLM to reach four families.

## Candidates being gated on vLLM

Recent, capable OSS models targeted for the results tier, pending an empirical pass on vLLM:

- Qwen3-32B (dense) and Qwen3-30B-A3B (MoE) — the Qwen3 models above, served natively on vLLM.
- Qwen2.5-Coder-32B-Instruct (AWQ) — strongest OSS coder at this size, for the code/repository suites.
- gemma-3-27b-it (AWQ) — confirm the Gemma result on vLLM.
- Mistral-Small-24B-Instruct (AWQ) — a fourth family.
- A reasoning model (QwQ-32B / DeepSeek-R1-Distill-Qwen-32B) for the reasoning slot.

This table is updated as models are gated.
