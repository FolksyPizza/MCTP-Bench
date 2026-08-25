# Models under evaluation

MCTP-Bench measures a context-transfer protocol, so the receiver models have to be able to perform
the tasks. A model that fails most tasks makes every condition look identical and hides any real
difference between the transcript, summary, RAG, and MCTP conditions. Every model therefore passes
a capability gate before it is admitted to the full suite. This page records what the evaluation
runs on, what passed, and what proved unsuitable.

## Capability gate

`scripts/capability_probe.sh <model> <url>` probes a model on a neutral sample (HumanEval and
GSM8K, transcript condition) and reports a pass rate against a threshold (default 40 percent). Only
models that clear the gate empirically are used for results; a strong reputation is not sufficient.
Reasoning models are given a larger generation budget so they finish thinking before answering.

## Serving

vLLM is the standard runner for all evaluation and results. It exposes an OpenAI-compatible server
and the harness talks to it over HTTP. On the GPU host, release 0.9.2 is used with the V0 engine
(`VLLM_USE_V1=0`) per `scripts/setup_vllm_wsl.sh`; models of 27B and larger are served
AWQ-quantized, one or two loaded at a time, at a 32K context window. Some earlier capability checks
used a single-stream serving path for convenience; those numbers are being re-confirmed on vLLM,
which is the system of record.

## Model tiers

- Telemetry and development tier (about 14B): fast, large-scale pipeline and throughput runs. Not
  used for final results.
- Results tier (20 to 35B, capability-gated): the models final results are reported on. The suite
  spans several model families for cross-model evidence and includes a reasoning model.

## Status

| Model | Family | Size | Served | Gate (HumanEval / GSM8K) | Status |
|-------|--------|------|--------|--------------------------|--------|
| Qwen3-32B-AWQ | Qwen3 | 32B | vLLM | 97% (14/15, 15/15) | Results tier |
| Qwen2.5-Coder-32B-AWQ | Qwen2.5 | 32B | vLLM | 93% (14/15, 14/15) | Results tier, code |
| Phi-4 | Phi | 14B | vLLM | 93% (14/15, 14/15) | Passes; strong for size |
| Gemma 3 27B | Gemma | 27B | single-stream | 92% (12/12, 10/12) | Candidate; vLLM re-gate pending |
| Qwen3 35B | Qwen3 | 35B | single-stream | 75% (6/12, 12/12) | Passes; weaker on code than the 27B |
| Qwen2.5-14B-Instruct | Qwen2.5 | 14B | vLLM | HumanEval 4/5 (sample) | Telemetry tier |
| GPT-OSS 20B | GPT-OSS | 20B | single-stream | server errors | Unsuitable in this environment |
| Qwen2.5-Coder-7B | Qwen2.5 | 7B | vLLM | near-zero on hard tasks | Below the results floor |

Notes:

- Larger is not automatically better. The 35B scored lower on code (6/12) than the 27B (12/12),
  which is why capability is gated empirically rather than assumed.
- Family breadth so far: Qwen3, Qwen2.5, and Phi are confirmed on vLLM. Gemma is a strong candidate
  pending its vLLM re-gate. A further family (Mistral) is planned to broaden the panel.

## Access

A Hugging Face token is configured on the host, so gated families (Gemma, Mistral, Llama) can be
served in addition to the open families (Qwen, Phi, Yi, InternLM, DeepSeek). Each gated model still
requires the account to have accepted its license before it will download.

## Candidates in progress

Recent, capable models targeted for the results tier, pending an empirical pass on vLLM:

- Qwen3-30B-A3B (mixture-of-experts): 30B-class quality at roughly 3B active parameters, for higher
  throughput on the large sweep.
- Gemma 3 27B (AWQ): confirm the earlier result on vLLM.
- Mistral-Small-24B-Instruct (AWQ): a further family.
- A reasoning model (QwQ-32B or DeepSeek-R1-Distill-Qwen-32B) for the reasoning slot.

This table is updated as models are gated.
