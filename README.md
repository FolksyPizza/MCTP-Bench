# MCTP-Bench

Evaluation harness for [MCTP](https://github.com/FolksyPizza/MCTP). It runs handoff
experiments as repeatable, scored episodes and measures whether MCTP maintains task
performance while reducing context cost.

## Run

```bash
python3 run.py                       # MockRunner over all scenarios x conditions
python3 run.py --real                # additionally include recorded model-in-the-loop episodes
python3 run.py --compare-tokenizers  # per-scenario token counts under every tokenizer
python3 run.py --tokenizer tiktoken:cl100k_base   # count with a specific tokenizer
```

The harness requires the Core MCTP package, located via `MCTP_HOME` (default: sibling
`../MCTP`). Override for a different checkout: `MCTP_HOME=/path/to/MCTP python3 run.py`.

Token counting uses real tokenizers when available (`mctpbench/tokenizers.py`): the tiktoken
OpenAI encodings and a chars/4 heuristic, with an optional Hugging Face hook for open-model
tokenizers. tiktoken is installed in the repository virtualenv, so run with `.venv/bin/python`
to count with it; under the system interpreter only the heuristic is available.

## Layout

```
mctpbench/
  episode.py      # episode record and JSONL logging
  conditions.py   # build flat vs mctp context from a scenario (Core selector/transfer)
  runner.py       # AgentRunner interface: MockRunner (deterministic) and RunResult
  harness.py      # run_episode(...) and record_real(...) for model-in-the-loop runs
  scoring.py      # aggregate report grouped by (scenario, condition, runner)
  tokenizers.py   # token counting: heuristic, tiktoken encodings, optional Hugging Face
scenarios/
  bug43.py               # coding handoff (Category 1)
  cache_staleness.py     # decision transfer (Category 2)
  auth_migration.py      # decision transfer (Category 2)
  artifact_selection.py  # artifact retrieval (Category 3)
  payment_idempotency.py # larger repository task, high token count (Category 4)
run.py           # CLI entry point
results/         # episodes.jsonl and verbatim agent transcripts
```

## Conditions

- `flat` — raw Agent-A transcript (everything inline, stale content included).
- `mctp` — Core cold-start selector packet plus a retrieve-on-demand blob map.

## Metrics

Accuracy (pass rate and gold sub-criteria), efficiency (context, retrieved, and total
tokens), behavior (pulls and codebase reads), and the MISLEADING count (whether provided
content caused an incorrect claim). A retrieve-on-demand pull is expected behavior; a
codebase read is a severe miss.

## Results

Single trial per condition, all runs using Claude models, task success judged by keyword-based
checks. Token counts use the tiktoken `o200k_base` encoding (see
`results/token_comparison.md` for other tokenizers). These are preliminary and are not a
statistical evaluation.

| Scenario | Condition | Pass | Context | Retrieved | Total | Pulls | Misleading |
|----------|-----------|------|---------|-----------|-------|-------|------------|
| bug43 | flat | 100% | 783 | 0 | 783 | 0 | 0 |
| bug43 | mctp | 100% | 420 | 93 | 513 | 1 | 0 |
| cache_staleness | flat | 100% | 557 | 0 | 557 | 0 | 0 |
| cache_staleness | mctp | 100% | 417 | 112 | 529 | 2 | 0 |
| auth_migration | flat | 100% | 291 | 0 | 291 | 0 | 0 |
| auth_migration | mctp | 100% | 341 | 95 | 436 | 2 | 0 |
| artifact_selection | flat | 100% | 184 | 0 | 184 | 0 | 0 |
| artifact_selection | mctp | 100% | 103 | 34 | 137 | 1 | 0 |
| payment_idempotency | flat | 100% | 2319 | 0 | 2319 | 0 | 0 |
| payment_idempotency | mctp | 100% | 486 | 159 | 645 | 2 | 0 |

Every cell passed the checks with no misleading answers, including both `flat` baselines.
Because the baseline also passed, these runs compare context cost at equal task success rather
than showing a correctness difference. On cost, MCTP reduced total tokens in four of five
scenarios and increased them in one; the effect scales with how much of the context is
prunable (`payment_idempotency` −72%, `auth_migration` +50%). See [docs/BENCHMARK.md](docs/BENCHMARK.md)
for the suite design and the [experiment record](https://github.com/FolksyPizza/MCTP/blob/main/docs/EXPERIMENTS.md)
in the MCTP repository for methodology and findings.

## Limitations

- `MockRunner` is deterministic and model-free; it validates the harness, not efficacy.
- Recorded episodes are single-trial, use only Claude models, and score with a keyword-based
  `check()`. Additional trials, scenarios, and model families are the next step.
- Token counts use tiktoken (OpenAI encodings) and the heuristic; open-model tokenizers are
  supported but were not exercised here.
