#!/usr/bin/env python3
"""The benchmark run plan: suites, model waves, trials, and the total test count.

Two waves run the whole program: first every suite on the small models, then the same on the
large models. Every wave includes a reasoning model, so reasoning is exercised on all scenarios.
Scoring is deferred to the cross-review ensemble pass (scoring/judge.py) after the runs.

    python bench_plan.py                # print the plan and the total counts
    python bench_plan.py --emit small   # print run_benchmark commands for the small wave
    python bench_plan.py --emit large   # ... the large wave

`ready=False` suites are counted but await their adapter/extractor; the emitter skips them.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

FOUR = ("transcript", "summary", "rag", "mctp")
LOW = ("transcript", "mctp")   # stateless suites: conditions coincide, so the pair suffices

TRIALS = 3
# Deferred cross-review scoring: judges x samples (round 1) + judges (cross-review) per output.
JUDGES = ["gemma3:27b", "qwen2.5:32b", "llama3.3:70b-instruct-q4"]  # mixed families
SAMPLES_PER_JUDGE = 2
JUDGE_CALLS_PER_OUTPUT = len(JUDGES) * SAMPLES_PER_JUDGE + len(JUDGES)  # +1 review call each


@dataclass
class Suite:
    name: str
    tier: str
    tasks: int
    conditions: tuple
    phase: int
    ready: bool = False
    agents_per_task: int = 1     # >1 for multi-agent swarm pipelines
    objective: bool = True       # has a programmatic scorer (judge is secondary if so)


@dataclass
class Wave:
    name: str
    models: list                 # list[(model_id, is_reasoning)]


SUITES = [
    # Every context type runs all four conditions (transcript/summary/rag/mctp), including the
    # low-context suites — for a uniform sweep, even though on stateless tasks the non-transcript
    # conditions largely coincide.
    Suite("humaneval", "low", 164, FOUR, phase=0, ready=True, objective=True),
    Suite("mbpp", "low", 500, FOUR, phase=0, ready=True, objective=True),
    Suite("gsm8k", "low", 500, FOUR, phase=0, ready=True, objective=True),
    Suite("inhouse", "medium", 10, FOUR, phase=1, ready=True, objective=False),
    Suite("multifile", "medium", 300, FOUR, phase=1, ready=True, objective=False),
    Suite("swebench", "high", 500, FOUR, phase=2, ready=True, objective=True),
    Suite("repobench", "high", 300, FOUR, phase=2, ready=True, objective=True),
    Suite("longbench", "high", 400, FOUR, phase=2, ready=True, objective=False),
    Suite("swarm", "subagent", 40, FOUR, phase=3, ready=True, agents_per_task=3,
          objective=False),
]

# Model suite: recent, capable OSS models in the 14-32B range that EMPIRICALLY clear the capability
# gate (scripts/capability_probe.sh) — chosen because they actually perform here, not because they
# are claimed to. Below ~14B most models fail too many tasks to distinguish conditions. Served at a
# lower context window (32K native, no rope scaling) — faster, fits comfortably, and covers the
# vast majority of tasks; the rare longer task is trimmed (recorded). The large wave's 32B models
# use AWQ to fit 2x24GB, 1-2 loaded at a time. Names are placeholders pending the gate; each wave
# spans families (Qwen, Gemma, ...) and includes a reasoning model (marked *).
WAVES = [
    Wave("capable", [("qwen2.5-14b", False), ("qwen2.5-coder-14b", False),
                     ("gemma2-9b", False), ("qwen3-14b", True)]),
    Wave("large", [("qwen2.5-32b-awq", False), ("qwen2.5-coder-32b-awq", False),
                   ("gemma3-27b", False), ("qwq-32b-awq", True)]),
]
CONTEXT_WINDOW = 32768   # served context per model (lower context, higher capability + speed)

# Model policy: a single-agent test (every suite except the multi-agent `swarm`) must run on at
# least this many distinct models, so any ASTP effect is shown to hold across models and is not a
# single-model artifact. The swarm suite already exercises multiple agent roles, so it is exempt.
MIN_MODELS_SINGLE_AGENT = 2

# Swarm agent arrangements per wave: same-family (one per family present) + cross-family. Computed
# from the wave model lists so the count stays in sync with the model suite.
from mctpbench.pipeline import build_arrangements  # noqa: E402

_ARR = {w.name: len(build_arrangements([m for m, _ in w.models])) for w in WAVES}
ARRANGEMENTS_TOTAL = sum(_ARR.values())


# Policy: large models are used only for single-agent suites (their strength is per-agent
# capability at high context), served 1-2 at a time at a 64-128K window. The multi-agent swarm
# tier uses the small-model wave only (cheap workers across roles), so swarm's arrangements come
# from the small wave alone.
SWARM_WAVE = "capable"


def _multiplier(suite: Suite, n_models: int, wave: str | None) -> int:
    """The model dimension: for swarm it is the number of agent arrangements (small wave only),
    otherwise the model count. `wave` selects a single wave's arrangements; None means both."""
    if suite.name == "swarm":
        return _ARR[SWARM_WAVE]
    return n_models


def receiver_runs(suite: Suite, n_models: int, wave: str | None = None) -> int:
    m = _multiplier(suite, n_models, wave)
    return suite.tasks * len(suite.conditions) * m * TRIALS * suite.agents_per_task


def _fmt(n: int) -> str:
    return f"{n:,}"


def print_plan():
    n_models_per_wave = len(WAVES[0].models)  # waves are the same width here
    total_models = sum(len(w.models) for w in WAVES)

    print("SUITES\n")
    hdr = f"{'suite':<18} {'tier':<9} {'phase':>5} {'tasks':>6} {'cond':>5} {'ready':>6} " \
          f"{'runs/wave':>10} {'runs(both waves)':>17}"
    print(hdr)
    print("-" * len(hdr))
    per_phase = {}
    total_recv = 0
    open_ended_outputs = 0
    for s in SUITES:
        rw = receiver_runs(s, n_models_per_wave, wave=WAVES[0].name)
        both = receiver_runs(s, total_models)
        total_recv += both
        outputs = both  # one output per receiver run
        if not s.objective:
            open_ended_outputs += outputs
        per_phase[s.phase] = per_phase.get(s.phase, 0) + both
        print(f"{s.name:<18} {s.tier:<9} {s.phase:>5} {s.tasks:>6} {len(s.conditions):>5} "
              f"{('yes' if s.ready else 'no'):>6} {_fmt(rw):>10} {_fmt(both):>17}")

    print(f"\nWAVES (trials={TRIALS}; reasoning model in each)")
    for w in WAVES:
        models = ", ".join(f"{m}{'*' if r else ''}" for m, r in w.models)
        has_reasoning = "ok" if any(r for _, r in w.models) else "MISSING"
        print(f"  {w.name:<6} ({len(w.models)} models, reasoning={has_reasoning})  {models}")
    print("  * = reasoning model")

    print("\nMODEL POLICY")
    print(f"  single-agent suites run on all {total_models} models across both waves "
          f"(>= {MIN_MODELS_SINGLE_AGENT} required, so an ASTP effect is cross-model, not a "
          f"single-model artifact)")
    print(f"  models are capability-gated (scripts/capability_probe.sh) and served at a "
          f"{CONTEXT_WINDOW // 1024}K window; large 32B (AWQ) models run single-agent suites only, "
          f"1-2 loaded at a time")
    print(f"  the multi-agent `swarm` suite uses the small-model wave only "
          f"({_ARR[SWARM_WAVE]} arrangements) — cheap workers across roles")
    small_ok = len(WAVES[0].models) >= MIN_MODELS_SINGLE_AGENT
    print(f"  smallest wave has {len(WAVES[0].models)} models: "
          f"{'satisfies' if small_ok else 'VIOLATES'} the >= {MIN_MODELS_SINGLE_AGENT} rule")

    ready_recv = sum(receiver_runs(s, total_models) for s in SUITES if s.ready)
    print("\nRECEIVER RUNS (tasks x conditions x models x trials x agents)")
    for ph in sorted(per_phase):
        print(f"  phase {ph}: {_fmt(per_phase[ph])}")
    print(f"  ready to run now (adapters built): {_fmt(ready_recv)}")
    print(f"  full program total:                {_fmt(total_recv)}")

    print("\nDEFERRED SCORING (cross-review ensemble, run after all receiver runs)")
    print(f"  judges: {len(JUDGES)} mixed-family, {SAMPLES_PER_JUDGE} samples each + 1 review "
          f"= {JUDGE_CALLS_PER_OUTPUT} judge calls per scored output")
    print(f"  scoring open-ended outputs only: {_fmt(open_ended_outputs * JUDGE_CALLS_PER_OUTPUT)} "
          f"judge calls")
    print(f"  scoring every output:            {_fmt(total_recv * JUDGE_CALLS_PER_OUTPUT)} "
          f"judge calls")
    print("\n  (objective suites are scored programmatically; judging them is a validation "
          "sample, not required.)")


def emit(wave_name: str):
    wave = next((w for w in WAVES if w.name == wave_name), None)
    if wave is None:
        raise SystemExit(f"unknown wave: {wave_name} (have: {[w.name for w in WAVES]})")
    models = ",".join(m for m, _ in wave.models)
    print(f"# {wave_name} wave — reasoning included; high --max-tokens so reasoners finish")
    for s in SUITES:
        if not s.ready:
            print(f"# (skip {s.name}: adapter/extractor not built)")
            continue
        conds = ",".join(s.conditions)
        print(f"python run_benchmark.py --suite {s.name} --models {models} "
              f"--conditions {conds} --trials {TRIALS} --max-tokens 4096 "
              f"--url http://localhost:8000/v1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", choices=[w.name for w in WAVES], help="print wave commands")
    args = ap.parse_args()
    if args.emit:
        emit(args.emit)
    else:
        print_plan()


if __name__ == "__main__":
    main()
