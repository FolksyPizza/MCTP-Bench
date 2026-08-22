"""The adapter contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from conditions import Source  # noqa: E402


# An objective scorer maps the receiver's answer text to (pass, detail). None when the suite
# has no programmatic scorer (open-ended tasks are left for the judge pass).
Objective = Optional[Callable[[str], "tuple[bool, dict]"]]


@dataclass
class Task:
    task_id: str
    source: Source
    receiver_instruction: str            # the question/prompt handed to the receiver
    objective: Objective = None
    gold: str = ""                       # reference answer or rubric (for the judge pass)
    reasoning_expected: bool = False
    meta: dict = field(default_factory=dict)


def source_from_repo(suite: str, task_id: str, task_text: str, repo: dict, tier: str = "large",
                     extractor: str = "heuristic", **extractor_kw) -> Source:
    """Build a Source for a repository task: run the extractor to get an MCTP graph (used by the
    `mctp` condition) and keep the raw files as a transcript/doc corpus (used by the other
    conditions). `repo` is {path -> content}."""
    from extraction import get_extractor
    store, tid = get_extractor(extractor, **extractor_kw).extract(repo, task_text, "task_main")
    graph = store.materialize()
    transcript = "\n\n".join(f"--- {p} ---\n{c}" for p, c in repo.items())
    return Source(suite=suite, task_id=task_id, task=task_text, tier=tier,
                  transcript=transcript, docs=dict(repo), graph=graph, graph_task_id=tid)


class Adapter:
    """Base class. Subclasses set `name`, `tier`, and implement `tasks`."""
    name = "adapter"
    tier = "small"
    default_conditions = ("transcript", "summary", "rag", "mctp")

    def tasks(self, limit: int | None = None) -> Iterable[Task]:
        raise NotImplementedError
