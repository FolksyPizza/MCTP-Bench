# MCTP-Bench Suite Design

This document defines the benchmark suite: its categories, the scenarios in each, and the
principles all scenarios follow. The suite favors a small number of strong, reproducible
scenarios over broad, shallow coverage.

## Design principles

1. Correctness is the primary metric. Token reduction is only meaningful when task
   capability is maintained; a scenario that reduces tokens but lowers pass rate is a
   regression.
2. Retrieval cost is counted. Reported cost is total tokens = initial context + retrieved
   tokens + any additional context requests, never the initial packet alone.
3. Reproducibility. Each episode records scenario, condition, runner, context tokens,
   retrieved tokens, total tokens, pass/fail, scoring criteria, and the relevant node/artifact
   ids (see `mctpbench/episode.py`).
4. The target is the best accuracy/cost tradeoff, not the smallest possible context. A
   scenario should be able to fail MCTP when the packet omits something the task needs.

## Conditions

Every scenario is evaluated under at least two conditions:

- `flat` — the raw Agent-A transcript (all content inline, stale material included).
- `mctp` — the Core selector packet (explicit state + artifact references) with
  retrieve-on-demand.

Two further baselines are planned so MCTP is compared against strong alternatives rather than
only a raw dump:

- `summary` — an LLM condenses Agent A's context into a handoff. The summarizer's own inference
  cost is counted in the total, not just the summary's token size.
- `rag` — the same source is stored and fetched with conventional vector retrieval.

Total cost for every condition is accounted the same way: Agent A inference + any preparation
inference (e.g. summarization) + retrieval/infrastructure + Agent B inference.

## Categories

### Category 1 — Coding handoff
Agent A investigates a bug; Agent B receives the handoff and produces the fix.
- Success criteria: correct mechanism, correct change site, correct rejected alternative.
- Failure modes: missing the change site; requesting the codebase because artifacts were
  summarized rather than referenced.
- Why MCTP should help: filters unrelated code and stale approaches; references the specific
  files and symbols B must change.
- Scenarios: `bug43` (implemented).

### Category 2 — Architecture decision transfer
Agent B must continue work without regressing to a rejected or superseded decision.
- Success criteria: adopts the current decision; identifies the rejected alternative and the
  reason; does not propose the superseded approach as the solution.
- Failure modes: recommending the abandoned approach (the MISLEADING label); losing the
  rationale for the current decision.
- Why MCTP should help: decisions carry supersession and rationale explicitly, and superseded
  decisions are excluded from the packet via the `supersedes` edge.
- Scenarios: `cache_staleness` (implemented), `auth_migration` (implemented).

### Category 3 — Artifact retrieval
The task references several files, but only some are needed. Tests whether references plus
targeted retrieval avoid inlining everything.
- Success criteria: correct answer; retrieves only the relevant artifact(s).
- Failure modes: retrieving unneeded artifacts (over-retrieval, a precision cost); failing
  because a needed artifact was neither referenced nor retrievable.
- Why MCTP should help: references let the receiver fetch only what the task requires instead
  of receiving all file contents inline.
- Scenarios: `artifact_selection` (implemented).

### Category 4 — Large repository tasks
Multi-file changes requiring dependency understanding and navigation across a larger graph.
- Success criteria: correct multi-file change plan; correct dependency ordering.
- Failure modes: missing a dependency edge; proposing a change that ignores a caller.
- Why MCTP should help: dependency relations are explicit, so the relevant subgraph can be
  transferred without the whole repository.
- Scenarios: `payment_idempotency` and `outage_investigation` (implemented) — ~2,300 and
  ~2,500-token investigations with several read-but-irrelevant files and superseded approaches.

### Category 5 — Multi-agent workflows
A research agent, an implementation agent, and a testing agent operate in sequence through
shared MCTP state.
- Success criteria: later agents do not re-derive context already established; final output
  is correct.
- Failure modes: repeated context transfer; coordination loss between stages.
- Why MCTP should help: shared state persists across agents, so downstream agents read from
  it rather than receiving a fresh transcript.
- Status: specified; not yet implemented. Requires an episode model spanning multiple
  handoffs.

## Implemented scenarios

| Scenario | Category | Task | Trap |
|----------|----------|------|------|
| `bug43` | 1 | Fix partition-migration data loss | superseded distributed-locking decision |
| `cache_staleness` | 2 | Fix distributed-cache stale reads | superseded TTL-tuning decision |
| `auth_migration` | 2 | Continue an auth migration | rejected session-cookie approach |
| `artifact_selection` | 3 | Answer a config question across many files | only one file is relevant |
| `payment_idempotency` | 4 | Fix duplicate charges in a large, noisy investigation | superseded lock and heuristic approaches |
| `schema_migration` | 4 | Zero-downtime column migration under hard constraints | superseded blocking ALTER and maintenance window |
| `api_versioning` | 2 | Implement v2 API authentication | superseded URL query-string token |
| `flaky_test` | 1 | Fix a time-dependent flaky test | superseded retry and sleep band-aids |
| `outage_investigation` | 4 | Fix a cascading outage (stampede + retry storm) | superseded scale-out and timeout increase |
| `hidden_constraint` | negative | Add a bulk-delete endpoint | required soft-delete constraint omitted from the packet |

Category 5 is specified above and left unimplemented pending the multi-handoff support it
requires. `hidden_constraint` is a negative control: the constraint needed to answer correctly
is present in the graph but not linked to the task, so the packet omits it and the mctp
condition fails — demonstrating that the suite can fail MCTP and that extraction/linking fidelity
is the ceiling.

## Scaling the benchmark

The ten in-house scenarios are illustrative controls with known ground truth and deliberate
traps. Scale — the goal is several hundred to a thousand tasks — comes from adapting existing
open-source benchmarks rather than authoring more in-house scenarios, so MCTP is measured on
independent tasks across a range of context sizes:

- Low context: function- or question-level tasks — HumanEval, MBPP (code), and short QA /
  reasoning sets (GSM8K, MMLU-style). Checks that structured transfer does not degrade tasks
  that are already well scoped.
- Medium context: multi-step or small multi-file tasks with moderate context.
- High context: real-repository and long-context tasks — SWE-bench / SWE-bench Verified (GitHub
  issue-to-patch on large repositories), RepoBench, and long-context suites (LongBench-style).
  This is the regime where MCTP is expected to help most.

Each external suite needs an adapter that (1) builds an MCTP graph from the task's repository or
context, (2) constructs the `flat` baseline from the same source, (3) runs both conditions
through a model runner, and (4) scores with the benchmark's own harness (unit tests, exact
match, or its judge) rather than the in-house keyword checks. Two prerequisites:

- A model runner against local or hosted inference. The `AgentRunner` interface and the Hugging
  Face tokenizer hook already provide the seam.
- An extractor that turns a real repository or transcript into an MCTP graph. The current
  scenarios hand-author their graphs; running external benchmarks at scale requires automatic
  extraction, which also finally exercises extraction fidelity — the system's ceiling — at scale
  (see the `hidden_constraint` finding and the negative control above).

Alongside scale, multi-trial runs and human- or judge-validated scoring will move results from
single-trial existence checks to statistically meaningful ones, and additional model families
will provide cross-model-family evidence.
