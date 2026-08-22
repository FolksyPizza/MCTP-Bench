"""Extractors: a real repository or transcript -> a Core MCTP graph.

The in-house scenarios hand-author their graphs; running external high-context suites at scale
requires turning a task's source (a repository snapshot, an issue, a transcript) into an MCTP
graph automatically. This is the system's ceiling — the `hidden_constraint` control showed that
a linking miss here, not the selector, is what fails MCTP — so extraction is measured, not
assumed.

Two extractors:

- `HeuristicExtractor` — deterministic and dependency-free: files become artifact nodes (path,
  content hash, language, parsed symbols) with import-derived `depends_on` edges, and the task
  is linked to the files it names. It has no notion of decisions or entities, so it is a floor,
  not a ceiling.
- `LLMExtractor` — prompts a model to emit nodes and edges (the closed v0.1 vocabulary) from the
  source, including decisions, superseded approaches, and constraints. This is the extractor
  whose fidelity bounds the system; it needs the model server and is not run here.

    get_extractor(name, **kw) -> Extractor
    extractor.extract(repo, task_text, task_id) -> (MCTPStore, task_id)
"""
from __future__ import annotations

from .base import Extractor


def get_extractor(name: str, **kw) -> Extractor:
    if name == "heuristic":
        from .heuristic import HeuristicExtractor
        return HeuristicExtractor(**kw)
    if name == "llm":
        from .llm import LLMExtractor
        return LLMExtractor(**kw)
    raise ValueError(f"unknown extractor: {name} (have: heuristic, llm)")


__all__ = ["Extractor", "get_extractor"]
