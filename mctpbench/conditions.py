"""Build the two handoff conditions for a scenario, from Core MCTP.

- flat: the raw Agent-A transcript (everything inline, stale included).
- mctp: the Core cold-start selector's structured packet + a retrievable blob map.
"""
from __future__ import annotations

from mctp import build_packet, cold_start_select

from . import tokenizers


def make_context(scenario, condition: str):
    """Return (context_text, retrievable, packet_node_ids, graph, task_id)."""
    store, task_id = scenario.build()
    graph = store.materialize()

    if condition == "flat":
        return scenario.flat_transcript, {}, [], graph, task_id

    if condition == "mctp":
        nodes = cold_start_select(graph, task_id)
        ctx = build_packet(graph, nodes, task_id)
        packet_ids = [n.id for n in nodes]
        retrievable = {
            n.id: graph.retrieve_artifact(n.id) for n in nodes if n.ref
        }
        return ctx, retrievable, packet_ids, graph, task_id

    raise ValueError(f"unknown condition: {condition}")


def tokens(text: str, tokenizer: str = tokenizers.HEURISTIC) -> int:
    return tokenizers.count(text, tokenizer)
