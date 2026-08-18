"""Orchestration: run a (scenario, condition, runner) into a scored Episode."""
from __future__ import annotations

from . import tokenizers
from .conditions import make_context, tokens
from .episode import Episode


def run_episode(scenario, condition: str, runner, tokenizer: str = tokenizers.HEURISTIC) -> Episode:
    ctx, retrievable, packet_ids, graph, task_id = make_context(scenario, condition)
    ctx_tokens = tokens(ctx, tokenizer)

    result = runner.run(
        task=graph.nodes[task_id].content, context=ctx, retrievable=retrievable
    )

    retrieved = [i for i in result.retrieved_ids if i in retrievable]
    retrieved_tokens = sum(tokens(retrievable[i], tokenizer) for i in retrieved)
    passed, criteria, misleading = scenario.check(result.answer)
    used = [i for i in packet_ids if i in result.answer]  # crude USED proxy (id in answer)

    return Episode(
        scenario=scenario.name, condition=condition,
        runner=getattr(runner, "name", "unknown"),
        context_tokens=ctx_tokens, packet_node_ids=packet_ids,
        retrieved_ids=retrieved, retrieved_tokens=retrieved_tokens,
        codebase_reads=result.codebase_reads, used_node_ids=used,
        outcome_pass=passed, criteria=criteria, misleading=misleading,
    )


def record_real(scenario, condition: str, runner: str, tokenizer: str, *,
                retrieved_ids=None, passed: bool, criteria=None, misleading=False) -> Episode:
    """Log an episode from a real model-in-the-loop run obtained out-of-band (Agent tool /
    API). Token counts are computed from the actual scenario contexts under `tokenizer`, so
    they update automatically when the tokenizer changes; the caller supplies only the
    observed behavior (which artifacts were pulled) and the scored outcome."""
    retrieved_ids = retrieved_ids or []
    ctx, retrievable, packet_ids, _graph, _task = make_context(scenario, condition)
    retrieved = [i for i in retrieved_ids if i in retrievable]
    return Episode(
        scenario=scenario.name, condition=condition, runner=runner,
        context_tokens=tokens(ctx, tokenizer), packet_node_ids=packet_ids,
        retrieved_ids=retrieved,
        retrieved_tokens=sum(tokens(retrievable[i], tokenizer) for i in retrieved),
        codebase_reads=0, used_node_ids=[],
        outcome_pass=passed, criteria=criteria or {}, misleading=misleading,
    )
