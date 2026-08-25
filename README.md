# MCTP-Bench

Evaluation harness for [MCTP](https://github.com/FolksyPizza/MCTP). It runs handoff
experiments as repeatable, scored episodes and measures whether MCTP maintains task
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
`MCTP_MODEL_URL`, `MCTP_MODEL`, and `MCTP_API_KEY` environment variables; the runner handles the
`RETRIEVE <id>` retrieve-on-demand round. `--limit N` runs only the first N scenarios (smoke
test). For reasoning models, raise the generation budget with `--max-tokens 4096` (or the
`MCTP_MAX_TOKENS` env var) so they finish thinking and reach the final answer; the runner reads
the answer from `content` and falls back to a `reasoning` field when present.

The harness requires the Core MCTP package, located via `MCTP_HOME` (default: sibling
`../MCTP`). Override for a different checkout: `MCTP_HOME=/path/to/MCTP python3 run.py`.

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
extraction/ # repo -> MCTP graph: heuristic.py (deterministic floor), llm.py (the ceiling)
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

- `flat`: raw Agent-A transcript (everything inline, stale content included).
- `mctp`, Core cold-start selector packet plus a retrieve-on-demand blob map.

## Metrics

Accuracy (pass rate and gold sub-criteria), efficiency (context, retrieved, and total
tokens), behavior (pulls and codebase reads), and the MISLEADING count (whether provided
content caused an incorrect claim). A retrieve-on-demand pull is expected behavior; a
codebase read is a severe miss.

## Results

Single trial per condition, all runs using Claude models, task success judged by keyword-based
checks. Token counts use the tiktoken `o200k_base` encoding (see `results/token_comparison.md`
for other tokenizers). These are preliminary and are not a statistical evaluation.

Across ten scenarios (20 conditions): the `flat` baseline passed all ten; the `mctp` condition
passed nine and failed one (`hidden_constraint`, where the packet omitted a required constraint
that was present in the transcript but not linked to the task). No misleading answers. On cost,
MCTP reduced total tokens in eight of ten scenarios and increased them in two; the effect scales
with how prunable the context is, from `outage_investigation` (-67%) and `payment_idempotency`
(-72%) on large, noisy transcripts to `auth_migration` (+50%) and `flaky_test` (+4%) on small,
already-concise ones. Per-scenario descriptions and numbers are in
[docs/SCENARIOS.md](docs/SCENARIOS.md); the full results table and methodology are in the
[experiment record](https://github.com/FolksyPizza/MCTP/blob/main/docs/EXPERIMENTS.md).

## Limitations

- `MockRunner` is deterministic and model-free; it validates the harness, not efficacy.
- Recorded episodes are single-trial, use only Claude models, and score with a keyword-based
 `check()`. Additional trials, scenarios, and model families are the next step.
- Token counts use tiktoken (OpenAI encodings) and the heuristic; open-model tokenizers are
 supported but were not exercised here.
