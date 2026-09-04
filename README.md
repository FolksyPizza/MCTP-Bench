# ASTP-Bench

Evaluation harness for [ASTP](https://github.com/FolksyPizza/ASTP). It runs handoff
experiments as repeatable, scored episodes and measures whether ASTP maintains task
performance while reducing context cost.

## Run

```bash
python3 run.py # MockRunner over all scenarios x conditions
python3 run.py --real # additionally include recorded model-in-the-loop episodes
python3 run.py --compare-tokenizers # per-scenario token counts under every tokenizer
python3 run.py --tokenizer tiktoken:cl100k_base # count with a specific tokenizer

# sweep a real model over an OpenAI-compatible endpoint (vLLM, Ollama, ...):
python3 run.py --model Qwen/Qwen2.5-32B-Instruct-AWQ --url http://SERVER:8000/v1 --trials 3
```

`--model` runs every scenario x condition (x `--trials`) through the endpoint and writes to
`results/model_runs.jsonl`, separate from the curated data. Configure via flags or the
`ASTP_MODEL_URL`, `ASTP_MODEL`, and `ASTP_API_KEY` environment variables; the runner handles the
`RETRIEVE <id>` retrieve-on-demand round. `--limit N` runs only the first N scenarios (smoke
test). For reasoning models, raise the generation budget with `--max-tokens 4096` (or the
`ASTP_MAX_TOKENS` env var) so they finish thinking and reach the final answer; the runner reads
the answer from `content` and falls back to a `reasoning` field when present.

The harness requires the Core ASTP package, located via `ASTP_HOME` (default: sibling
`../ASTP`). Override for a different checkout: `ASTP_HOME=/path/to/ASTP python3 run.py`.

Token counting uses real tokenizers when available (`mctpbench/tokenizers.py`): the tiktoken
OpenAI encodings and a chars/4 heuristic, with an optional Hugging Face hook for open-model
tokenizers. tiktoken is installed in the repository virtualenv, so run with `.venv/bin/python`
to count with it; under the system interpreter only the heuristic is available.

## Layout

```
mctpbench/
 episode.py # episode record and JSONL logging (in-house scenario path)
 conditions.py # build flat vs mctp context from a scenario (Core selector/transfer)
 runner.py # AgentRunner interface: MockRunner + OpenAICompatRunner
 streaming.py # StreamingRunner: raw capture + per-token timeline + native usage
 records.py # RunRecord schema and ResultStore (the storage tree)
 pipeline.py # multi-handoff runner for the swarm tier (state threaded across stages)
 orchestrate.py # checkpoint/resume, ETA/progress, time-window and pause/stop control
 telemetry.py # live status over a localhost socket (for monitor.py)
 harness.py # run_episode(...) and record_real(...) for model-in-the-loop runs
 scoring.py # aggregate report grouped by (scenario, condition, runner)
 tokenizers.py # token counting: heuristic, tiktoken encodings, optional Hugging Face
scenarios/ # ten scenarios; see docs/SCENARIOS.md for what each does
adapters/ # suites: humaneval, mbpp, gsm8k, swebench, repobench, longbench, inhouse, swarm
conditions/ # builders: transcript, summary (same-model), rag (TF-IDF), mctp (Core packet)
scoring/ # objective scorers (unit tests / exact match / line match) + cross-review judge
extraction/ # repo -> ASTP graph: heuristic.py (deterministic floor), llm.py (the ceiling)
run.py # in-house scenario CLI
run_benchmark.py # large-scale matrix runner (suite x models x conditions x trials)
bench_plan.py # the run plan: suites, model waves, trials, total run count
monitor.py # live dashboard: connects to the runner's telemetry socket
analyze.py # pricing + committed aggregate tables
scripts/ # host setup and dataset fetch (run on the GPU host)
results/ # the storage tree (see docs/DATA-MODEL.md)
```

The large-scale framework (`run_benchmark.py`, `adapters/`, `conditions/`, `scoring/`) records
full raw + parsed data per run; see [docs/BENCHMARK.md](docs/BENCHMARK.md) and
[docs/DATA-MODEL.md](docs/DATA-MODEL.md). Validate it offline with no server via
`python run_benchmark.py --suite humaneval --dry-run`.

## Conditions

Four handoff strategies compared head to head, plus an experimental fifth:

- `transcript`: the full accumulated context inline (stale content included).
- `summary`: a same-model summarization of that context (its inference cost is counted).
- `rag`: TF-IDF retrieval over that context.
- `mctp`: the Core believed-state packet, selected to a token budget, with retrieve-on-demand.
- `mctp-r`: ASTP with relevance-ranked selection (retrieval inside the believed-state packet).

## Metrics

Accuracy (objective pass rate and gold sub-criteria), efficiency (context, retrieved, and total
tokens), latency and decode speed, and behavior (retrieve-on-demand pulls and codebase reads).
A pull is expected behavior; a codebase read is a severe miss. Every run keeps a full audit
trail: the exact prompt, the output, the per-token timeline, and the raw request and response.

## Results

Each suite runs under the conditions above on local open-weights models. The strongest results
are on long-context and multi-agent handoffs, where an explicit, provenance-tracked believed-state
holds up as work passes from one agent to the next in ways that a summary or plain retrieval
cannot. Interim results for a capable open-weights model across the completed suites, pairing pass
rate with context cost, are in [docs/RESULTS.md](docs/RESULTS.md), updated as the run completes.

## Limitations

- `MockRunner` is deterministic and model-free; it validates the harness, not efficacy.
- Results so far are one capable open-weights model plus two small models, at a single trial for
  the large model; more models, more trials, and the deferred judge pass are in progress.
- repobench and swebench are not yet reportable (a completion-prompt fix and native scoring,
  respectively); scoring is otherwise automated (execution for code, robust matching for QA).
