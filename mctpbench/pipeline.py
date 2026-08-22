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


def run_pipeline(store, swarm_task, condition, model, trial, runner, tok, *, summarizer=None,
                 endpoint="", temperature=0.0, seed=1, max_tokens=None) -> list:
    """Run one swarm task under one condition, threading state across stages. Returns the list
    of per-stage RunRecords."""
    from run_benchmark import execute_run  # lazy import to avoid a module cycle
    from conditions import Source

    transcript = f"PROJECT BRIEF\n{swarm_task.brief}"
    mstore = MCTPStore()
    clock = [0]

    def prov():
        clock[0] += 1
        return Provenance("swarm", "pipeline", model, clock[0])

    mstore.assert_node("task_goal", "task", swarm_task.brief, prov())
    prev_out = None
    records = []

    for i, stage in enumerate(swarm_task.stages):
        tsid = f"task_s{i}"
        if condition == "mctp":
            mstore.assert_node(tsid, "task", stage.instruction, prov())
            mstore.assert_edge(tsid, "task_goal", "relates_to", prov())
            if prev_out:
                mstore.assert_edge(tsid, prev_out, "relates_to", prov())
            src = Source(suite="swarm", task_id=tsid, task=stage.instruction, tier="subagent",
                         graph=mstore.materialize(), graph_task_id=tsid)
        else:
            src = Source(suite="swarm", task_id=tsid, task=stage.instruction, tier="subagent",
                         transcript=transcript)

        rec, answer = execute_run(
            store, suite="swarm", task_id=f"{swarm_task.task_id}/s{i}_{stage.role}",
            tier="subagent", source=src, condition=condition, model=model, trial=trial,
            runner=runner, tok=tok, instruction=stage.receiver_instruction,
            objective=stage.objective, summarizer=summarizer, endpoint=endpoint,
            temperature=temperature, seed=seed, max_tokens=max_tokens)
        records.append(rec)

        transcript += f"\n\n=== {stage.role} output ===\n{answer}"
        if condition == "mctp":
            oid = f"out_s{i}"
            mstore.assert_node(oid, "decision", answer, prov())
            mstore.assert_edge(oid, tsid, "derived_from", prov())
            prev_out = oid

    return records
