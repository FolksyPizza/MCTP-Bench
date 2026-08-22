"""The four condition builders, plus a registry.

    build(source, condition, *, summarizer=None) -> Built

Only `summary` uses `summarizer` (a callable text -> (summary_text, prep_tokens)); the runner
binds it to the same model as the receiver so the summarizer's inference is counted, per the
data model. The others are deterministic.
"""
from __future__ import annotations

from .retrieval import TfidfRetriever, chunk
from .source import Built, Source


def _prior_text(source: Source) -> str:
    """The prior-agent context as plain text: an explicit transcript, or the doc corpus."""
    if source.transcript:
        return source.transcript
    if source.docs:
        return "\n\n".join(f"[{k}]\n{v}" for k, v in source.docs.items())
    return ""


def build_transcript(source: Source, **_) -> Built:
    return Built(condition="transcript", text=_prior_text(source))


def build_summary(source: Source, *, summarizer=None, **_) -> Built:
    prior = _prior_text(source)
    if not prior:
        return Built(condition="summary", text="")
    if summarizer is None:
        # Deterministic stand-in for dry runs: no model available, so no real summary.
        head = " ".join(prior.split()[:120])
        return Built(condition="summary", text=head,
                     meta={"summarizer": "none (dry-run truncation)"})
    summary, prep = summarizer(prior)
    return Built(condition="summary", text=summary, prep_tokens=prep,
                 meta={"summarizer": "same-model"})


def build_rag(source: Source, *, top_k=4, **_) -> Built:
    prior = _prior_text(source)
    if not prior:
        return Built(condition="rag", text="")
    chunks = chunk(prior)
    if not chunks:
        return Built(condition="rag", text="")
    hits = TfidfRetriever(chunks).search(source.task, k=top_k)
    selected = [chunks[i] for i, _ in hits]
    text = "\n\n".join(f"[chunk {i}]\n{chunks[i]}" for i, _ in hits)
    return Built(condition="rag", text=text,
                 meta={"chunks_total": len(chunks), "chunks_selected": len(selected),
                       "scores": [round(s, 4) for _, s in hits]})


def build_mctp(source: Source, **_) -> Built:
    """Core selector packet. Uses a prebuilt graph when the Source carries one; otherwise
    wraps the bare task as a minimal single-node packet (stateless suites, pre-extractor)."""
    if source.graph is not None and source.graph_task_id is not None:
        from mctp import build_packet, cold_start_select
        graph = source.graph
        task_id = source.graph_task_id
        nodes = cold_start_select(graph, task_id)
        text = build_packet(graph, nodes, task_id)
        packet_ids = [n.id for n in nodes]
        retrievable = {n.id: graph.retrieve_artifact(n.id) for n in nodes if n.ref}
        return Built(condition="mctp", text=text, retrievable=retrievable,
                     packet_node_ids=packet_ids)
    # No graph: the packet is just the task as current state. Honest for stateless tasks.
    text = f"STATE\n- task: {source.task}"
    return Built(condition="mctp", text=text, packet_node_ids=[source.task_id],
                 meta={"note": "minimal packet (no graph; extractor not yet applied)"})


CONDITIONS = {
    "transcript": build_transcript,
    "summary": build_summary,
    "rag": build_rag,
    "mctp": build_mctp,
}


def build(source: Source, condition: str, *, summarizer=None, top_k=4) -> Built:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition: {condition} (have {sorted(CONDITIONS)})")
    return CONDITIONS[condition](source, summarizer=summarizer, top_k=top_k)
