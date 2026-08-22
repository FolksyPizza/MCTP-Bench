# MCTP-Bench Data Model

What every benchmark run records, how it is stored, and how it is scored. The goal is to preserve
everything — full model output, chain-of-thought, token counts, second-by-second timing, and
scores — so analysis and pricing can be redone later without re-running any model.

## Principles

- Capture raw and parsed, additively. Store the exact request(s), the complete unmodified server
  response(s), and the timestamped output stream verbatim, AND the parsed/derived fields (extracted
  answer, reasoning, token counts, timing) alongside them. Both are kept: the parsed fields make
  analysis convenient, and the raw capture guarantees any analysis, scoring, or pricing can be
  redone from the bare data. Nothing is discarded.
- Record everything, score and price later. Each run captures its full input, output, reasoning,
  token counts, and timing at run time, plus an objective pass/fail where the suite provides a
  scorer. Judge scores and cost are computed in separate passes over the stored records, so we
  never re-run models to re-score or re-price.
- Immutable and append-only. Run records are never edited; derived judge scores and aggregates
  reference them by `run_id`.

## The run record

One record per (suite, task, condition, model, trial):

```
{
  "run_id": "<uuid>",
  "suite": "swebench", "task_id": "...", "tier": "large",
  "condition": "mctp",               # transcript | summary | rag | mctp | mctp-learned
  "model": "qwen3.6:35b", "model_size_b": 35, "reasoning": true,
  "trial": 1, "started_at": "<iso8601>",

  # input delivered to the receiver
  "prompt_ref": "outputs/<run_id>.prompt.txt",   # large text stored as a file
  "context_tokens": 503, "packet_node_ids": [...],

  # MCTP behavior
  "retrieved_ids": [...], "retrieved_tokens": 325, "codebase_reads": 0,

  # output — everything the model produced
  "output_ref": "outputs/<run_id>.out.txt",      # the final answer text
  "reasoning_ref": "outputs/<run_id>.think.txt", # chain-of-thought, if any
  "prompt_tokens": 503, "reasoning_tokens": 1840, "output_tokens": 240,  # model's native tokenizer
  "ref_token_counts": {"tiktoken:o200k_base": {...}, "tiktoken:cl100k_base": {...}, "hf:<model>": {...}},

  # timing (see below)
  "t_start": 0.0, "ttft_s": 0.31, "t_end": 6.7, "latency_s": 6.7,
  "timeline_ref": "outputs/<run_id>.timeline.jsonl",

  # objective score (suite scorer, when one exists)
  "objective_pass": true, "objective_detail": {...},

  # provenance / reproducibility
  "runner": "vllm", "endpoint": "...", "temperature": 0.0, "seed": 1,
  "model_digest": "...", "harness_commit": "...",
  "raw_ref": "raw/<run_id>.jsonl"    # verbatim request(s) + full response(s) + streamed chunks
}
```

The parsed fields above are kept for convenient analysis; the raw capture referenced by `raw_ref`
is stored alongside them as the authoritative source (see below). Both are retained.

## Raw capture

For every run, stored verbatim and never post-processed at capture time:

- The exact request payload(s) sent to the model server — messages, model, temperature, seed,
  `max_tokens`, and any other parameters — for the initial call and each retrieve-on-demand round.
- The complete server response object(s) as received — all fields, including `usage`, `finish_reason`,
  any `reasoning`/`thinking` field, and provider-specific extras — nothing dropped.
- The timestamped output stream: every streamed chunk with the wall-clock offset at which it
  arrived, so the exact text present at any second of the run is reconstructable.

Everything else in the record (extracted answer, reasoning, token counts, timing, scores) is
derived from this raw capture, so analysis, scoring, and pricing can be redone from the bare data
without re-running any model.

## Tokenization

Token counts are recorded two ways. The model's native counts come from the server's `usage`
field — the model's own tokenizer — and are authoritative for that model's cost; on the GPU host
the model's Hugging Face tokenizer is available and is used when the server does not report usage.
In addition, reference counts are computed over the same text with a fixed set of tokenizers
(the tiktoken encodings and selected model tokenizers) so token amounts are comparable across
models that tokenize differently. Each record logs the exact model id, size, digest, and start
time, so every count is attributable to a specific model at a specific moment.

Large text (prompt, output, reasoning, timeline) is stored as referenced files so the JSONL stays
scannable; small deployments may inline them.

## Timing (second-by-second)

Runs use the streaming API so each generated chunk is timestamped. `timeline_ref` points to a
JSONL of `[offset_seconds, text]` entries, from which time-to-first-token, tokens/second, and a
reconstruction of exactly what each condition had produced at any moment are derived. This
supports "which condition was ahead" analysis over the course of a run.

## Storage layout

```
results/
  runs/         run records, sharded JSONL: <suite>/<model>/<condition>.jsonl
  raw/          verbatim request payload(s), full server response(s), and streamed chunks per run
  outputs/      referenced text derived from raw: prompts, answers, reasoning, token timelines
  judge/        ensemble judge scores, one record per (run_id, judge_model)
  aggregates/   computed tables and analysis graphs
  configs/      exact batch configs: models, seeds, prompts, suite + harness versions
```

`results/runs/`, `results/raw/`, and `results/outputs/` are gitignored (large) and published as a
dataset release; `results/aggregates/` and `results/configs/` are committed so the paper's tables
are reproducible.

## Execution

For large-scale gathering the harness runs co-located with the model server on the GPU host: it
queries the local endpoint (no network tunnel), streams responses with low latency, and writes all
raw data and records to the host's disk (hundreds of GB free). Long sweeps run detached so they
survive disconnects. Only the small committed artifacts (`results/aggregates/`, `results/configs/`)
are synced back to the repository; the large raw dataset (`results/runs|raw|outputs/`) stays on the
host and is published as a dataset release. Development and calibration may run the harness remotely
against a tunneled endpoint, but the recorded runs are produced on the host.

This requires the MCTP and MCTP-Bench repositories and a Python environment (with the tokenizer
dependency) on the host, alongside the model server.

## Objective scoring (at run time)

Where a suite has an objective scorer (unit tests, exact match), it runs when the record is
written and sets `objective_pass`. Open-ended tasks are left unscored for the judge pass.

## Deferred cross-review judging (a separate pass, after all runs)

All receiver runs are recorded first; scoring is a separate pass that never re-runs a receiver.
The pass (`scoring/judge.py`) has three stages and stores every judge input/output, so the
scoring itself is auditable and can be re-aggregated:

1. Independent scoring — an ensemble of at least three judge models, chosen from different
   families to reduce self-preference bias, each scores every output `samples_per_judge` times
   (two by default) at nonzero temperature. The two samples expose a judge's own instability.
2. Cross-review — each judge is then shown the other judges' assessments and asked to critique
   them and give a final judgment, so an outlier can be corrected and disagreement is surfaced.
3. Aggregation — the final label is the majority vote over the post-review pass/fail and the
   median of the post-review scores. Inter-judge disagreement, sample instability, and the
   round-1→round-2 score shift are recorded alongside.

Each run gets one file in `results/judge/` holding all round-1 samples, all cross-review
verdicts (with raw judge text), and the aggregate. The ensemble is validated against a
human-labeled sample. This replaces keyword scoring, which a 27B model was already able to
false-pass. Suites with a programmatic scorer (unit tests, exact match) are judged only as a
validation sample; open-ended outputs are judged in full.

## Cost and pricing (at analysis time)

Cost is not stored; token counts are. Standard per-token prices are applied later from a pricing
table, so pricing can change without re-running anything. Per-run cost =
`prompt_tokens + reasoning_tokens + output_tokens`, plus the summarizer's tokens for the `summary`
condition and embedding/retrieval for `rag`, priced per model.

## Model tiers

- Small / medium runs: 8–14B models.
- Large / strongest tests: 27–35B models (no larger than 35B).
- Judges: an ensemble of at least three, from mixed families.
- Summarizer: the same model as the receiver (an agent summarizing its own state); its inference
  is counted in the `summary` condition's cost.

## Implementation

The run store and streaming runner are implemented:

- `mctpbench/streaming.py` — `StreamingRunner` runs a model over the OpenAI-compatible endpoint
  with `stream=true`, capturing the exact request(s), every streamed chunk with its wall-clock
  offset, the server's `usage` block (native token counts), and the assembled answer/reasoning.
  It populates `timeline_ref`, `ttft_s`, and per-token timing, and handles the retrieve-on-demand
  rounds.
- `mctpbench/records.py` — `RunRecord` (the schema above) and `ResultStore`, which writes the raw
  capture, the referenced text under `outputs/`, the reference token counts, and the parsed record
  into the storage tree.
- `run_benchmark.py` — the matrix runner (suite × models × conditions × trials) that assembles and
  writes each record; `--dry-run` exercises the whole pipeline with a deterministic runner and no
  server. `analyze.py` applies pricing and writes the committed aggregates.

The ensemble judge (`scoring/judge.py`) is a separate pass over the stored records, run after the
model runs complete.
