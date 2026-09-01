"""The four condition builders, plus a registry.

    build(source, condition, *, summarizer=None) -> Built

Only `summary` uses `summarizer` (a callable text -> (summary_text, prep_tokens)); the runner
binds it to the same model as the receiver so the summarizer's inference is counted, per the
data model. The others are deterministic.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mctpbench import tokenizers  # noqa: E402

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


def build_mctp(source: Source, *, budget_tokens=None, **_) -> Built:
    """Core selector packet. Uses a prebuilt graph when the Source carries one; otherwise
    wraps the bare task as a minimal single-node packet (stateless suites, pre-extractor).

    Hybrid delivery, budget-aware: the selector first drops the least load-bearing, most distant
    nodes to fit `budget_tokens` (an intelligent trim vs the transcript's naive head+tail). Then,
    for the selected artifacts, content that FITS the remaining budget is inlined directly (so a
    document the task genuinely needs is delivered in full, no wasted retrieve round), and only
    content that would overflow the budget is left as a reference to pull on demand. With no budget
    every artifact is a reference (the original behavior). The token win therefore comes from
    excluding irrelevant nodes and deferring overflow — not from starving the receiver of context
    it needs."""
    if source.graph is not None and source.graph_task_id is not None:
        from mctp import cold_start_select
        nodes = cold_start_select(source.graph, source.graph_task_id, budget_tokens=budget_tokens)
        return _mctp_built(source.graph, source.graph_task_id, nodes, "mctp", budget_tokens)
    # No graph: the packet is just the task as current state. Honest for stateless tasks.
    text = f"STATE\n- task: {source.task}"
    return Built(condition="mctp", text=text, packet_node_ids=[source.task_id],
                 meta={"note": "minimal packet (no graph; extractor not yet applied)"})


def _mctp_built(graph, task_id, nodes, condition, budget_tokens) -> Built:
    """Build the delivered packet from selected nodes: inline artifact content that fits the
    remaining budget, leave overflow as retrieve-on-demand references. Shared by the mctp
    conditions."""
    from mctp import build_packet
    text = build_packet(graph, nodes, task_id)
    packet_ids = [n.id for n in nodes]
    retrievable, inlined = {}, []
    used = tokenizers.count(text, tokenizers.default())
    for n in nodes:
        if not n.ref:
            continue
        content = graph.retrieve_artifact(n.id)
        ctoks = tokenizers.count(content, tokenizers.default())
        if budget_tokens and used + ctoks <= budget_tokens:
            text += f"\n\n[ARTIFACT {n.id} — {n.ref.get('path', '')}]\n{content}"
            used += ctoks
            inlined.append(n.id)
        else:
            retrievable[n.id] = content   # overflow: pull on demand
    return Built(condition=condition, text=text, retrievable=retrievable,
                 packet_node_ids=packet_ids,
                 meta={"inlined": inlined, "referenced": list(retrievable)})


def build_mctp_r(source: Source, *, budget_tokens=None, top_k=4, **_) -> Built:
    """Retrieval-augmented MCTP: the same believed-state packet, but the budget is filled by
    relevance to the task rather than by hop distance. The task and decision nodes are still
    guaranteed (the provenance a plain retriever cannot reconstruct); the supporting artifacts and
    entities are ranked with the same TF-IDF retriever the `rag` condition uses. RAG inside MCTP."""
    if source.graph is not None and source.graph_task_id is not None:
        from mctp import cold_start_select
        graph = source.graph
        node_ids = list(graph.nodes)
        contents = [graph.nodes[nid].content or "" for nid in node_ids]
        relevance = None
        if any(c.strip() for c in contents):
            retr = TfidfRetriever(contents)
            scores = {nid: 0.0 for nid in node_ids}
            for idx, s in retr.search(source.task, k=len(contents)):
                scores[node_ids[idx]] = s
            relevance = lambda n: scores.get(n.id, 0.0)  # noqa: E731
        nodes = cold_start_select(graph, source.graph_task_id, budget_tokens=budget_tokens,
                                  relevance=relevance)
        return _mctp_built(graph, source.graph_task_id, nodes, "mctp-r", budget_tokens)
    text = f"STATE\n- task: {source.task}"
    return Built(condition="mctp-r", text=text, packet_node_ids=[source.task_id],
                 meta={"note": "minimal packet (no graph; extractor not yet applied)"})


CONDITIONS = {
    "transcript": build_transcript,
    "summary": build_summary,
    "rag": build_rag,
    "mctp": build_mctp,
    "mctp-r": build_mctp_r,
}


def build(source: Source, condition: str, *, summarizer=None, top_k=4, budget_tokens=None) -> Built:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition: {condition} (have {sorted(CONDITIONS)})")
    return CONDITIONS[condition](source, summarizer=summarizer, top_k=top_k,
                                 budget_tokens=budget_tokens)
