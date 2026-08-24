"""Multi-handoff pipeline runner — the subagent/swarm tier.

A swarm task is an ordered sequence of stages (for example research -> implementation ->
testing) that share evolving state. Each stage is a handoff: the receiver for stage i sees the
state accumulated by stages 0..i-1, in the representation the condition under test dictates, and
its output is folded back into that state for the next stage. Each stage is recorded as its own
run, so the cost of carrying state forward is captured per stage — which is the point of the
tier: as the pipeline grows, the `transcript` condition re-sends everything while `mctp` sends a
selected packet, and the per-stage context tokens show the difference.

Every condition threads its own state: `transcript` accumulates the raw stage outputs; `mctp`
accumulates nodes in an MCTP store and selects a packet per stage; `summary`/`rag` operate over
the accumulated transcript.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mctpbench  # noqa: F401  (bootstraps MCTP_HOME)

from mctp import MCTPStore, Provenance  # noqa: E402

_FAMILIES = ["qwen", "llama", "gemma", "phi", "mistral", "deepseek", "gpt", "yi"]


def family_of(model: str) -> str:
    m = model.lower()
    for fam in _FAMILIES:
        if fam in m:
            return fam
    return "other"


def build_arrangements(models: list, kinds=("same", "cross"), n_stages: int = 3) -> list:
    """Build swarm agent arrangements from the available models. Returns [(name, [model_per_stage])].

    - same-<family>: every stage run by models of one family (cycled across sizes if several) —
      the homogeneous baseline.
    - cross-family: stages drawn from different families (one per family, round-robin) — the
      heterogeneous case, where accumulated inter-agent state is largest because the agents share
      no implicit lineage. Requires at least two families among the models."""
    byfam = {}
    for m in models:
        byfam.setdefault(family_of(m), []).append(m)
    arrangements = []
    if "same" in kinds:
        for fam, ms in byfam.items():
            arrangements.append((f"same-{fam}", [ms[i % len(ms)] for i in range(n_stages)]))
    if "cross" in kinds and len(byfam) >= 2:
        reps = [ms[0] for ms in byfam.values()]
        arrangements.append(("cross-family", [reps[i % len(reps)] for i in range(n_stages)]))
    if not arrangements:
        arrangements.append(("solo", [models[0]] * n_stages))
    return arrangements


def run_pipeline(store, swarm_task, condition, model, trial, runner, tok, *, summarizer=None,
                 endpoint="", temperature=0.0, seed=1, max_tokens=None,
                 stage_models=None, runner_for=None, arrangement=None,
                 max_context_tokens=0) -> list:
    """Run one swarm task under one condition, threading state across stages. Returns the list
    of per-stage RunRecords.

    Agent arrangement: by default every stage is run by the same `model`/`runner`. Passing
    `stage_models` (one model id per stage) plus `runner_for` (model id -> runner) assigns a
    different model per role — so a pipeline can be run same-family (all stages one family) or
    cross-family (stages from different families), which is where accumulated inter-agent state
    matters most. `arrangement` labels the configuration and is folded into each record's task_id
    so arrangements are distinct in the manifest and results."""
    from run_benchmark import execute_run  # lazy import to avoid a module cycle
    from conditions import Source

    n = len(swarm_task.stages)
    stage_models = stage_models or [model] * n
    tag = f"#{arrangement}" if arrangement else ""

    transcript = f"PROJECT BRIEF\n{swarm_task.brief}"
    mstore = MCTPStore()
    clock = [0]

    def prov(m):
        clock[0] += 1
        return Provenance("swarm", "pipeline", m, clock[0])

    mstore.assert_node("task_goal", "task", swarm_task.brief, prov(stage_models[0]))
    prev_out = None
    records = []

    for i, stage in enumerate(swarm_task.stages):
        stage_model = stage_models[i]
        stage_runner = runner_for(stage_model) if runner_for else runner
        stage_summ = (stage_runner.summarize if condition == "summary"
                      and hasattr(stage_runner, "summarize") else None)
        tsid = f"task_s{i}"
        if condition == "mctp":
            mstore.assert_node(tsid, "task", stage.instruction, prov(stage_model))
            mstore.assert_edge(tsid, "task_goal", "relates_to", prov(stage_model))
            if prev_out:
                mstore.assert_edge(tsid, prev_out, "relates_to", prov(stage_model))
            src = Source(suite="swarm", task_id=tsid, task=stage.instruction, tier="subagent",
                         graph=mstore.materialize(), graph_task_id=tsid)
        else:
            src = Source(suite="swarm", task_id=tsid, task=stage.instruction, tier="subagent",
                         transcript=transcript)

        stage_endpoint = getattr(stage_runner, "base_url", endpoint) or endpoint
        rec, answer = execute_run(
            store, suite="swarm", task_id=f"{swarm_task.task_id}{tag}/s{i}_{stage.role}",
            tier="subagent", source=src, condition=condition, model=stage_model, trial=trial,
            runner=stage_runner, tok=tok, instruction=stage.receiver_instruction,
            objective=stage.objective, summarizer=stage_summ, endpoint=stage_endpoint,
            temperature=temperature, seed=seed, max_tokens=max_tokens,
            max_context_tokens=max_context_tokens)
        records.append(rec)

        transcript += f"\n\n=== {stage.role} ({stage_model}) output ===\n{answer}"
        if condition == "mctp":
            oid = f"out_s{i}"
            mstore.assert_node(oid, "decision", answer, prov(stage_model))
            mstore.assert_edge(oid, tsid, "derived_from", prov(stage_model))
            prev_out = oid

    return records
