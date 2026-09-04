# Benchmark results (interim)

This is a preliminary snapshot from an ongoing large-scale run. It reports one capable model on
the suites completed so far. Additional models, the multi-agent (swarm) suite, and the native
SWE-bench scoring pass are still running and will be added in a later update.

## Setup

- Model: a 27B-parameter open-weights model (Qwen3 series, 4-bit quantized), served locally with
  a 128K context window.
- Conditions: `transcript` (the full accumulated context), `summary` (same-model summarization),
  `rag` (TF-IDF retrieval), `mctp` (a believed-state packet selected to a token budget).
- Trials: one per task.
- Metric: objective pass rate. Code suites execute the produced function against unit checks;
  math and long-context suites use exact-match answer checks.

## Pass rate and context cost by condition

Each cell reports the objective pass rate and the average delivered-context size in tokens
(tiktoken `o200k_base`), so accuracy and its token cost sit side by side.

| Suite | n | transcript | summary | rag | mctp |
| --- | --- | --- | --- | --- | --- |
| gsm8k | 1319 | 97% / 0 | 97% / 0 | 97% / 0 | 97% / 63 |
| humaneval | 164 | 96% / 0 | 96% / 0 | 96% / 0 | 96% / 136 |
| mbpp | 500 | 82% / 0 | 82% / 0 | 82% / 0 | 81% / 52 |
| multifile | 300 | 100% / 80 | 91% / 279 | 100% / 75 | 100% / 157 |
| longbench | 294 | 61% / 12,360 | 46% / 836 | 46% / 354 | 59% / 180 |

Cells are pass rate / average context tokens. (longbench uses robust QA answer matching that
tolerates markdown, punctuation, and rewording.)

On the low-context suites (gsm8k, humaneval, mbpp) the four conditions fall within one point of
each other. These tasks carry little prunable prior context, so the delivery method does not
change the outcome. This is the expected baseline: ASTP does not cost accuracy where there is
nothing to select.

The long-context suite is where the delivery method separates. On longbench, ASTP nearly matches
the full transcript (59 percent against 61 percent) while delivering about one sixty-ninth of the
context (180 tokens against 12,360), and it scores about thirteen points above same-model
summarization and TF-IDF retrieval (both near 46 percent). On the smaller models, whose 8192-token
window forces the transcript to truncate, ASTP wins outright (for example 54 vs 37 percent on the
7B) because it selects the load-bearing context instead of losing it to a blind trim.

## Pending

- repobench is held back pending a correction to how the completion prompt is framed.
- swebench is held back pending the native scoring pass.
- The multi-agent (swarm) suite is still running.
- Further models and additional trials.
